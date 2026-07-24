#!/usr/bin/env python3
"""
Export the whole OrgIQ scan portfolio from a Salesforce org into the dashboard's
bundled data file.

    python3 dashboard/export_portfolio.py --target-org orgiq \
        --out dashboard/public/portfolio.json

Three queries (scans, dimension scores, findings), grouped in Python by the
scan's external id. The app computes all portfolio- and org-level metrics from
this raw shape.
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict


def query(soql, org):
    proc = subprocess.run(
        ["sf", "data", "query", "--query", soql, "--target-org", org,
         "--result-format", "json"], capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if proc.returncode != 0 or payload.get("status", 1) != 0:
        sys.exit(f"query failed: {payload.get('message', proc.stderr)}")
    return payload["result"]["records"]


def dim_code(name):
    return name.split(" ", 1)[0]


def dim_short(name):
    return name.split(" ", 1)[1] if " " in name else name


def density_share(pct):
    """Semantic_Density__c is a Salesforce Percent, so the org holds 42.5 for
    42.5%. Everything downstream — scan_result's "semantic_density", the
    dashboard — speaks the 0-1 share, so convert once here instead of leaving
    every reader to guess which unit it got."""
    return None if pct is None else pct / 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    org = a.target_org

    scans = query(
        "SELECT Name, External_Scan_Id__c, Target_Org__c, Scan_Mode__c, "
        "Rubric_Version__c, Composite_Score__c, Readiness_Band__c, "
        "Components_Scanned__c, Semantic_Density__c, Est_Grounding_Tokens__c, "
        "Est_Remediated_Tokens__c, Gate_Applied__c, Gate_Reason__c, Scan_Timestamp__c "
        "FROM OrgIQ_Scan__c ORDER BY Composite_Score__c ASC", org)

    dims = query(
        "SELECT Scan__r.External_Scan_Id__c, Dimension__c, Score__c, "
        "Rule_Coverage__c, In_Composite__c, Assessment_Status__c, Missing_Signals__c "
        "FROM OrgIQ_Dimension_Score__c", org)

    findings = query(
        "SELECT Scan__r.External_Scan_Id__c, External_Finding_Id__c, Rule_Id__c, "
        "Dimension__c, Severity__c, Confidence__c, Component_Type__c, "
        "Component_Api_Name__c, Evidence__c, Remediation__c, Epic__c, "
        "Acceptance_Criteria__c, Source__c, Effort_Points__c, "
        "Blast_Radius__c, Emits_To_Backlog__c, Rule_Maturity__c, Status__c "
        "FROM OrgIQ_Finding__c", org)

    dims_by_scan = defaultdict(list)
    for d in dims:
        dims_by_scan[d["Scan__r"]["External_Scan_Id__c"]].append({
            "code": dim_code(d["Dimension__c"]),
            "name": dim_short(d["Dimension__c"]),
            "fullName": d["Dimension__c"],
            "score": d["Score__c"],
            "coverage": d["Rule_Coverage__c"],
            "inComposite": d["In_Composite__c"],
            "status": d["Assessment_Status__c"],
            "missingSignals": d["Missing_Signals__c"] or "",
        })

    finds_by_scan = defaultdict(list)
    for f in findings:
        finds_by_scan[f["Scan__r"]["External_Scan_Id__c"]].append({
            "externalId": f["External_Finding_Id__c"],
            "ruleId": f["Rule_Id__c"],
            "dimension": f["Dimension__c"],
            "severity": f["Severity__c"],
            "confidence": f["Confidence__c"],
            "componentType": f["Component_Type__c"],
            "component": f["Component_Api_Name__c"],
            "evidence": f["Evidence__c"] or "",
            "remediation": f["Remediation__c"] or "",
            # Blank rather than a default: the dashboard's RULE_META mirror is
            # the fallback, and an invented value here would hide an org whose
            # findings predate these fields.
            "epic": f["Epic__c"] or "",
            "acceptanceCriteria": f["Acceptance_Criteria__c"] or "",
            "source": f["Source__c"] or "",
            "effortPoints": f["Effort_Points__c"],
            "blastRadius": f["Blast_Radius__c"],
            "emitsToBacklog": f["Emits_To_Backlog__c"],
            "ruleMaturity": f["Rule_Maturity__c"],
            "status": f["Status__c"],
        })

    out = {"source": "salesforce", "scans": []}
    for s in scans:
        sid = s["External_Scan_Id__c"]
        dim_rows = sorted(dims_by_scan[sid], key=lambda d: d["code"])
        out["scans"].append({
            "scan": {
                "name": s["Name"],
                "externalId": sid,
                "targetOrg": s["Target_Org__c"],
                "scanMode": s["Scan_Mode__c"],
                "rubricVersion": s["Rubric_Version__c"],
                "compositeScore": s["Composite_Score__c"],
                "readinessBand": s["Readiness_Band__c"],
                "componentsScanned": s["Components_Scanned__c"],
                "semanticDensity": density_share(s["Semantic_Density__c"]),
                "estGroundingTokens": s["Est_Grounding_Tokens__c"],
                "estRemediatedTokens": s["Est_Remediated_Tokens__c"],
                "gateApplied": s["Gate_Applied__c"],
                "gateReason": s["Gate_Reason__c"] or "",
                "timestamp": s["Scan_Timestamp__c"],
            },
            "dimensions": dim_rows,
            "findings": finds_by_scan[sid],
        })

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    nf = sum(len(s["findings"]) for s in out["scans"])
    print(f"wrote {a.out}: {len(out['scans'])} scans, {nf} findings")


if __name__ == "__main__":
    main()
