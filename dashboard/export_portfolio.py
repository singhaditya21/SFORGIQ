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

    enterprises = query(
        "SELECT External_Enterprise_Id__c, Name, Industry__c, Notes__c "
        "FROM OrgIQ_Enterprise__c ORDER BY Name", org)

    scans = query(
        "SELECT Name, External_Scan_Id__c, Enterprise_Id__c, Target_Org__c, Scan_Mode__c, "
        "Rubric_Version__c, Composite_Score__c, Readiness_Band__c, "
        "Components_Scanned__c, Semantic_Density__c, Est_Grounding_Tokens__c, "
        "Est_Remediated_Tokens__c, Removable_Restating__c, Removable_Duplicates__c, Removable_Unreferenced__c, Gate_Applied__c, Gate_Reason__c, Scan_Timestamp__c "
        "FROM OrgIQ_Scan__c ORDER BY Composite_Score__c ASC", org)

    dims = query(
        "SELECT Scan__r.External_Scan_Id__c, Dimension__c, Score__c, "
        "Rule_Coverage__c, In_Composite__c, Assessment_Status__c, Missing_Signals__c "
        "FROM OrgIQ_Dimension_Score__c", org)

    findings = query(
        "SELECT Scan__r.External_Scan_Id__c, External_Finding_Id__c, Rule_Id__c, "
        "Dimension__c, Severity__c, Confidence__c, Component_Type__c, "
        "Component_Api_Name__c, Evidence__c, Remediation__c, Epic__c, "
        "Acceptance_Criteria__c, Source__c, Effort_Points__c, Effort_Basis__c, Actual_Effort_Points__c, "
        "Blast_Radius__c, Emits_To_Backlog__c, Rule_Maturity__c, Status__c, "
        "Survived_Scans__c, Resolved_In_Scan__c, Owner_Role__c "
        "FROM OrgIQ_Finding__c", org)

    personas = query(
        "SELECT Scan__r.External_Scan_Id__c, Name, Persona_Kind__c, Summary__c, "
        "Unbounded__c, Blanket_Perms__c, Reach__c, Objects_Editable__c, "
        "Objects_Readable__c, Objects_Deletable__c, Fields_Visible__c, "
        "Fields_Available__c, Flows__c, Approvals__c, Blocked_By__c, Actions__c, "
        "Editable_Objects__c, Flow_Names__c, Blocking_Rules__c "
        "FROM OrgIQ_Persona__c ORDER BY Unbounded__c DESC, Reach__c DESC", org)

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
            "effortBasis": f["Effort_Basis__c"] or "",
            "actualEffort": f["Actual_Effort_Points__c"],
            "blastRadius": f["Blast_Radius__c"],
            "emitsToBacklog": f["Emits_To_Backlog__c"],
            "ruleMaturity": f["Rule_Maturity__c"],
            "status": f["Status__c"],
            # null, not 0, where no scan history could establish a run — the
            # dashboard has to be able to say "not measured" rather than "new".
            "ownerRole": f["Owner_Role__c"] or "",
            "survivedScans": f["Survived_Scans__c"],
            "resolvedInScan": f["Resolved_In_Scan__c"] or "",
        })

    def splitlist(text):
        return [p for p in (text or "").split(" | ") if p]

    personas_by_scan = defaultdict(list)
    for p in personas:
        personas_by_scan[p["Scan__r"]["External_Scan_Id__c"]].append({
            "name": p["Name"],
            "kind": p["Persona_Kind__c"],
            "summary": p["Summary__c"] or "",
            "unbounded": p["Unbounded__c"],
            "blanketPerms": p["Blanket_Perms__c"] or "",
            "reach": p["Reach__c"],
            "objectsEditable": p["Objects_Editable__c"],
            "objectsReadable": p["Objects_Readable__c"],
            "objectsDeletable": p["Objects_Deletable__c"],
            # Genuinely null for a permission set — see the field's own note.
            "fieldsVisible": p["Fields_Visible__c"],
            "fieldsAvailable": p["Fields_Available__c"],
            "flows": p["Flows__c"],
            "approvals": p["Approvals__c"],
            "blockedBy": p["Blocked_By__c"],
            "actions": p["Actions__c"],
            "editableObjects": splitlist(p["Editable_Objects__c"]),
            "flowNames": splitlist(p["Flow_Names__c"]),
            "blockingRules": splitlist(p["Blocking_Rules__c"]),
        })

    out = {"source": "salesforce",
           # Named records, not prefixes recovered from an org name.
           "enterprises": [{"id": e["External_Enterprise_Id__c"], "name": e["Name"],
                            "industry": e["Industry__c"] or "",
                            "notes": e["Notes__c"] or ""} for e in enterprises],
           "scans": []}
    for s in scans:
        sid = s["External_Scan_Id__c"]
        dim_rows = sorted(dims_by_scan[sid], key=lambda d: d["code"])
        out["scans"].append({
            "scan": {
                "name": s["Name"],
                "externalId": sid,
                "enterpriseId": s["Enterprise_Id__c"],
                "targetOrg": s["Target_Org__c"],
                "scanMode": s["Scan_Mode__c"],
                "rubricVersion": s["Rubric_Version__c"],
                "compositeScore": s["Composite_Score__c"],
                "readinessBand": s["Readiness_Band__c"],
                "componentsScanned": s["Components_Scanned__c"],
                "semanticDensity": density_share(s["Semantic_Density__c"]),
                "estGroundingTokens": s["Est_Grounding_Tokens__c"],
                "estRemediatedTokens": s["Est_Remediated_Tokens__c"],
                "estRemovableTokens": {
                    "restating_descriptions": s["Removable_Restating__c"] or 0,
                    "duplicate_clusters": s["Removable_Duplicates__c"] or 0,
                    "unreferenced_fields": s["Removable_Unreferenced__c"] or 0,
                },
                "gateApplied": s["Gate_Applied__c"],
                "gateReason": s["Gate_Reason__c"] or "",
                "timestamp": s["Scan_Timestamp__c"],
            },
            "dimensions": dim_rows,
            "findings": finds_by_scan[sid],
            "personas": personas_by_scan[sid],
        })

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    nf = sum(len(s["findings"]) for s in out["scans"])
    np_ = sum(len(s["personas"]) for s in out["scans"])
    print(f"wrote {a.out}: {len(out['scans'])} scans, {nf} findings, "
          f"{np_} persona surfaces")


if __name__ == "__main__":
    main()
