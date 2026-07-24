#!/usr/bin/env python3
"""
Load an OrgIQ scan result JSON into a Salesforce org via the `sf` CLI (Bulk API).

    python3 salesforce/load_scan.py scan_result.json --target-org orgiq

Idempotent:
  - OrgIQ_Scan__c and OrgIQ_Finding__c are upserted on their External_*_Id__c
    fields, so re-running updates the same records instead of duplicating.
  - OrgIQ_Dimension_Score__c has no external id, so its rows for this scan are
    deleted and re-inserted.

Read-only against any *target* org is a project invariant — but note this writes
to the OrgIQ org itself (the findings store), which is the intended destination.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCAN_OBJ = "OrgIQ_Scan__c"
FINDING_OBJ = "OrgIQ_Finding__c"
DIM_OBJ = "OrgIQ_Dimension_Score__c"


def sf(args: list[str]) -> dict:
    """Run an sf command with --json, return the parsed result, raise on error."""
    proc = subprocess.run(["sf", *args, "--json"], capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        sys.exit(f"sf {' '.join(args)}\nnon-JSON output:\n{proc.stdout}\n{proc.stderr}")
    if proc.returncode != 0 or payload.get("status", 1) != 0:
        sys.exit(f"sf {' '.join(args)} failed:\n"
                 f"{payload.get('message', proc.stderr or proc.stdout)}")
    return payload.get("result", {})


def _write_csv(path: Path, columns: list[str], rows: list[dict]):
    # Bulk API 2.0 defaults to LF line endings on macOS/Linux; Python's csv
    # writer defaults to CRLF, which the job rejects. Force LF here. Embedded
    # newlines inside quoted fields (remediation text) are preserved fine.
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def _b(v) -> str:
    return "true" if v else "false"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_json")
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--wait", default="10")
    a = ap.parse_args()

    data = json.loads(Path(a.scan_json).read_text())
    scan, dims, findings = data["scan"], data["dimensions"], data["findings"]
    org = a.target_org
    tmp = Path(tempfile.mkdtemp(prefix="orgiq-load-"))

    # 1) Upsert the Scan on its external id -------------------------------
    scan_cols = ["External_Scan_Id__c", "Target_Org__c", "Scan_Mode__c",
                 "Rubric_Version__c", "Composite_Score__c", "Readiness_Band__c",
                 "Components_Scanned__c", "Gate_Applied__c", "Gate_Reason__c",
                 "Scan_Timestamp__c"]
    _write_csv(tmp / "scan.csv", scan_cols, [{
        "External_Scan_Id__c": scan["external_scan_id"],
        "Target_Org__c": scan["target_org"],
        "Scan_Mode__c": scan["scan_mode"],
        "Rubric_Version__c": scan["rubric_version"],
        "Composite_Score__c": scan["composite_score"],
        "Readiness_Band__c": scan["readiness_band"],
        "Components_Scanned__c": scan["components_scanned"],
        "Gate_Applied__c": _b(scan["gate_applied"]),
        "Gate_Reason__c": scan["gate_reason"],
        "Scan_Timestamp__c": scan["scan_timestamp"],
    }])
    print("→ upserting scan…")
    sf(["data", "upsert", "bulk", "--sobject", SCAN_OBJ, "--file",
        str(tmp / "scan.csv"), "--external-id", "External_Scan_Id__c",
        "--target-org", org, "--wait", a.wait])

    q = sf(["data", "query", "--query",
            f"SELECT Id FROM {SCAN_OBJ} WHERE External_Scan_Id__c="
            f"'{scan['external_scan_id']}'", "--target-org", org])
    scan_id = q["records"][0]["Id"]
    print(f"  scan Id = {scan_id}")

    # 2) Upsert Findings on their external id -----------------------------
    f_cols = ["External_Finding_Id__c", "Scan__c", "Rule_Id__c", "Dimension__c",
              "Severity__c", "Confidence__c", "Component_Type__c",
              "Component_Api_Name__c", "Evidence__c", "Remediation__c",
              "Effort_Points__c", "Blast_Radius__c", "Emits_To_Backlog__c",
              "Rule_Maturity__c", "Status__c"]
    f_rows = [{
        "External_Finding_Id__c": f["external_finding_id"],
        "Scan__c": scan_id,
        "Rule_Id__c": f["rule_id"],
        "Dimension__c": f["dimension"],
        "Severity__c": f["severity"],
        "Confidence__c": f["confidence"],
        "Component_Type__c": f["component_type"],
        "Component_Api_Name__c": f["component_api_name"],
        "Evidence__c": f["evidence"],
        "Remediation__c": f["remediation"],
        "Effort_Points__c": f["effort_points"],
        "Blast_Radius__c": f["blast_radius"],
        "Emits_To_Backlog__c": _b(f["emits_to_backlog"]),
        "Rule_Maturity__c": f["rule_maturity"],
        "Status__c": f["status"],
    } for f in findings]
    _write_csv(tmp / "findings.csv", f_cols, f_rows)
    print(f"→ upserting {len(f_rows)} findings…")
    sf(["data", "upsert", "bulk", "--sobject", FINDING_OBJ, "--file",
        str(tmp / "findings.csv"), "--external-id", "External_Finding_Id__c",
        "--target-org", org, "--wait", a.wait])

    # 3) Replace Dimension Scores (no external id) ------------------------
    existing = sf(["data", "query", "--query",
                   f"SELECT Id FROM {DIM_OBJ} WHERE Scan__c='{scan_id}'",
                   "--target-org", org])
    old = existing.get("records", [])
    if old:
        _write_csv(tmp / "dim_del.csv", ["Id"], [{"Id": r["Id"]} for r in old])
        print(f"→ deleting {len(old)} existing dimension score(s)…")
        sf(["data", "delete", "bulk", "--sobject", DIM_OBJ, "--file",
            str(tmp / "dim_del.csv"), "--target-org", org, "--wait", a.wait])

    d_cols = ["Scan__c", "Dimension__c", "Score__c", "Rule_Coverage__c",
              "In_Composite__c", "Assessment_Status__c", "Missing_Signals__c"]
    d_rows = [{
        "Scan__c": scan_id,
        "Dimension__c": d["dimension"],
        "Score__c": "" if d["score"] is None else d["score"],
        "Rule_Coverage__c": d["rule_coverage"],
        "In_Composite__c": _b(d["in_composite"]),
        "Assessment_Status__c": d["assessment_status"],
        "Missing_Signals__c": d["missing_signals"],
    } for d in dims]
    _write_csv(tmp / "dims.csv", d_cols, d_rows)
    print(f"→ inserting {len(d_rows)} dimension scores…")
    sf(["data", "import", "bulk", "--sobject", DIM_OBJ, "--file",
        str(tmp / "dims.csv"), "--target-org", org, "--wait", a.wait])

    print(f"\nloaded scan {scan['external_scan_id']} into {org}: "
          f"1 scan, {len(f_rows)} findings, {len(d_rows)} dimension scores")


if __name__ == "__main__":
    main()
