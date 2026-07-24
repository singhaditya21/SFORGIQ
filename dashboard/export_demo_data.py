#!/usr/bin/env python3
"""
Export an OrgIQ scan from a Salesforce org into the dashboard's demo data file.

    python3 dashboard/export_demo_data.py --target-org orgiq \
        --out dashboard/public/sample-scan.json

This queries the live org (the same read path a logged-in dashboard would use)
and writes public/sample-scan.json, which the app bundles for demo mode — so the
public GitHub Pages site shows real, previously-loaded scan data with no login.
"""

import argparse
import json
import subprocess
import sys


def query(soql: str, org: str) -> list[dict]:
    proc = subprocess.run(
        ["sf", "data", "query", "--query", soql, "--target-org", org, "--json"],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if proc.returncode != 0 or payload.get("status", 1) != 0:
        sys.exit(f"query failed: {payload.get('message', proc.stderr)}")
    return payload["result"]["records"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--external-scan-id", default=None,
                    help="which scan to export (default: the most recent)")
    a = ap.parse_args()
    org = a.target_org

    where = (f"WHERE External_Scan_Id__c='{a.external_scan_id}'"
             if a.external_scan_id else "")
    scans = query(
        "SELECT Name, External_Scan_Id__c, Target_Org__c, Scan_Mode__c, "
        "Rubric_Version__c, Composite_Score__c, Readiness_Band__c, "
        "Components_Scanned__c, Gate_Applied__c, Gate_Reason__c, Scan_Timestamp__c "
        f"FROM OrgIQ_Scan__c {where} ORDER BY Scan_Timestamp__c DESC LIMIT 1", org)
    if not scans:
        sys.exit("no scan found in org")
    s = scans[0]
    scan_id_soql = f"WHERE Scan__r.External_Scan_Id__c='{s['External_Scan_Id__c']}'"

    dims = query(
        "SELECT Dimension__c, Score__c, Rule_Coverage__c, In_Composite__c, "
        "Assessment_Status__c, Missing_Signals__c "
        f"FROM OrgIQ_Dimension_Score__c {scan_id_soql} ORDER BY Dimension__c", org)

    findings = query(
        "SELECT External_Finding_Id__c, Rule_Id__c, Dimension__c, Severity__c, "
        "Confidence__c, Component_Type__c, Component_Api_Name__c, Evidence__c, "
        "Remediation__c, Effort_Points__c, Blast_Radius__c, Emits_To_Backlog__c, "
        f"Rule_Maturity__c, Status__c FROM OrgIQ_Finding__c {scan_id_soql}", org)

    def dim_code(name):
        return name.split(" ", 1)[0]           # "D1 Grounding Quality" -> "D1"

    def dim_short(name):
        return name.split(" ", 1)[1] if " " in name else name

    out = {
        "source": "salesforce",
        "org": s["Target_Org__c"],
        "scan": {
            "name": s["Name"],
            "externalId": s["External_Scan_Id__c"],
            "targetOrg": s["Target_Org__c"],
            "scanMode": s["Scan_Mode__c"],
            "rubricVersion": s["Rubric_Version__c"],
            "compositeScore": s["Composite_Score__c"],
            "readinessBand": s["Readiness_Band__c"],
            "componentsScanned": s["Components_Scanned__c"],
            "gateApplied": s["Gate_Applied__c"],
            "gateReason": s["Gate_Reason__c"] or "",
            "timestamp": s["Scan_Timestamp__c"],
        },
        "dimensions": [{
            "code": dim_code(d["Dimension__c"]),
            "name": dim_short(d["Dimension__c"]),
            "fullName": d["Dimension__c"],
            "score": d["Score__c"],
            "coverage": d["Rule_Coverage__c"],
            "inComposite": d["In_Composite__c"],
            "status": d["Assessment_Status__c"],
            "missingSignals": d["Missing_Signals__c"] or "",
        } for d in dims],
        "findings": [{
            "externalId": f["External_Finding_Id__c"],
            "ruleId": f["Rule_Id__c"],
            "dimension": f["Dimension__c"],
            "severity": f["Severity__c"],
            "confidence": f["Confidence__c"],
            "componentType": f["Component_Type__c"],
            "component": f["Component_Api_Name__c"],
            "evidence": f["Evidence__c"] or "",
            "remediation": f["Remediation__c"] or "",
            "effortPoints": f["Effort_Points__c"],
            "blastRadius": f["Blast_Radius__c"],
            "emitsToBacklog": f["Emits_To_Backlog__c"],
            "ruleMaturity": f["Rule_Maturity__c"],
            "status": f["Status__c"],
        } for f in findings],
    }

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {a.out}: 1 scan, {len(out['findings'])} findings, "
          f"{len(out['dimensions'])} dimensions (composite "
          f"{out['scan']['compositeScore']} / {out['scan']['readinessBand']})")


if __name__ == "__main__":
    main()
