#!/usr/bin/env python3
"""
Load an OrgIQ scan result JSON into a Salesforce org via the `sf` CLI (Bulk API).

    python3 salesforce/load_scan.py scan_result.json --target-org orgiq

Idempotent:
  - OrgIQ_Scan__c and OrgIQ_Finding__c are upserted on their External_*_Id__c
    fields, so re-running updates the same records instead of duplicating.
  - OrgIQ_Dimension_Score__c has no external id, so its rows for this scan are
    deleted and re-inserted.

A re-scan is treated as a full restatement of a scan's findings (step 3): what
this run no longer reports is retired to Resolved, what it reports again is
reopened, and anything a human Suppressed is left alone. Status__c is never sent
on the upsert itself, so human triage survives a re-run.

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

# Statuses the loader will not overwrite. Suppressed is a human saying "we know,
# we accept it" — the scanner has no standing to undo that, in either direction.
HUMAN_HOLD = {"Suppressed"}


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


def _density_pct(ratio) -> float:
    """Semantic_Density__c is a Percent(3,1) — Salesforce stores 42.5 for 42.5%
    — while the scan JSON carries a 0..1 ratio. 99.9 is the field's ceiling, so
    a perfectly dense corpus is clamped rather than failing the whole job."""
    return min(round(float(ratio) * 100, 1), 99.9)


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

    # uniqueness guard ----------------------------------------------------
    # Bulk API 2.0 rejects a batch that repeats an external id, and a collision
    # would also mean two findings share one record. Checked before anything is
    # written, so a bad JSON costs nothing. The set doubles as the "what this
    # run reported" side of the lifecycle diff in step 3.
    loaded = {f["external_finding_id"] for f in findings}
    if len(loaded) != len(findings):
        sys.exit(f"duplicate external_finding_id in {a.scan_json} "
                 f"({len(findings) - len(loaded)} collisions)")

    # 1) Upsert the Scan on its external id -------------------------------
    scan_cols = ["External_Scan_Id__c", "Target_Org__c", "Scan_Mode__c",
                 "Rubric_Version__c", "Composite_Score__c", "Readiness_Band__c",
                 "Components_Scanned__c", "Semantic_Density__c",
                 "Est_Grounding_Tokens__c", "Est_Remediated_Tokens__c",
                 "Gate_Applied__c", "Gate_Reason__c", "Scan_Timestamp__c"]
    _write_csv(tmp / "scan.csv", scan_cols, [{
        "External_Scan_Id__c": scan["external_scan_id"],
        "Target_Org__c": scan["target_org"],
        "Scan_Mode__c": scan["scan_mode"],
        "Rubric_Version__c": scan["rubric_version"],
        "Composite_Score__c": scan["composite_score"],
        "Readiness_Band__c": scan["readiness_band"],
        "Components_Scanned__c": scan["components_scanned"],
        "Semantic_Density__c": _density_pct(scan["semantic_density"]),
        "Est_Grounding_Tokens__c": scan["est_grounding_tokens"],
        "Est_Remediated_Tokens__c": scan["est_remediated_tokens"],
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
    #
    # Status__c is deliberately NOT in this list. It used to be, which meant
    # every re-run stamped every finding back to Open and wiped whatever triage
    # a human had done. The field now defaults to Open on insert, so leaving it
    # out gives new findings the right status and leaves existing ones alone.
    f_cols = ["External_Finding_Id__c", "Scan__c", "Rule_Id__c", "Dimension__c",
              "Severity__c", "Confidence__c", "Component_Type__c",
              "Component_Api_Name__c", "Evidence__c", "Epic__c",
              "Remediation__c", "Acceptance_Criteria__c", "Effort_Points__c",
              "Blast_Radius__c", "Source__c", "Emits_To_Backlog__c",
              "Rule_Maturity__c"]
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
        "Epic__c": f["epic"],
        "Remediation__c": f["remediation"],
        "Acceptance_Criteria__c": f["acceptance_criteria"],
        "Effort_Points__c": f["effort_points"],
        "Blast_Radius__c": f["blast_radius"],
        "Source__c": f["source"],
        "Emits_To_Backlog__c": _b(f["emits_to_backlog"]),
        "Rule_Maturity__c": f["rule_maturity"],
    } for f in findings]
    _write_csv(tmp / "findings.csv", f_cols, f_rows)
    print(f"→ upserting {len(f_rows)} findings…")
    sf(["data", "upsert", "bulk", "--sobject", FINDING_OBJ, "--file",
        str(tmp / "findings.csv"), "--external-id", "External_Finding_Id__c",
        "--target-org", org, "--wait", a.wait])

    # 3) Reconcile the lifecycle against what this run reported ------------
    #
    # A re-scan restates the whole scan, so the diff is the burn-down: findings
    # still attached to this scan but absent from this run have been fixed
    # (Resolved), and a previously-retired finding that fires again has
    # regressed (back to Open). Without this the record set only ever grows and
    # old and new findings are indistinguishable.
    current = sf(["data", "query", "--query",
                  f"SELECT Id, External_Finding_Id__c, Status__c "
                  f"FROM {FINDING_OBJ} WHERE Scan__c='{scan_id}'",
                  "--target-org", org]).get("records", [])
    # Filtered here rather than in SOQL: NOT IN has surprising null semantics,
    # and the rows are already in hand.
    moves = []
    for r in current:
        status = r.get("Status__c")
        if status in HUMAN_HOLD:
            continue
        seen = r["External_Finding_Id__c"] in loaded
        if not seen and status != "Resolved":
            moves.append({"Id": r["Id"], "Status__c": "Resolved"})
        elif seen and status == "Resolved":
            moves.append({"Id": r["Id"], "Status__c": "Open"})
    if moves:
        retired = sum(1 for m in moves if m["Status__c"] == "Resolved")
        _write_csv(tmp / "lifecycle.csv", ["Id", "Status__c"], moves)
        print(f"→ retiring {retired} finding(s), reopening {len(moves) - retired}…")
        sf(["data", "update", "bulk", "--sobject", FINDING_OBJ, "--file",
            str(tmp / "lifecycle.csv"), "--target-org", org, "--wait", a.wait])

    # 4) Replace Dimension Scores (no external id) ------------------------
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
          f"1 scan, {len(f_rows)} findings, {len(d_rows)} dimension scores, "
          f"{len(moves)} status change(s)")


if __name__ == "__main__":
    main()
