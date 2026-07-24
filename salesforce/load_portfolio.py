#!/usr/bin/env python3
"""
Bulk-load a whole portfolio of scans (from scan_portfolio.py) into a Salesforce
org. Wipes existing OrgIQ scans first, then inserts everything with one Bulk API
job per object — fast even for a couple thousand findings.

    python3 salesforce/load_portfolio.py portfolio.json --target-org orgiq

The portfolio JSON is {"scans": [ {scan, dimensions, findings}, ... ]}.

Because every record is deleted and re-inserted, there is no finding lifecycle
to reconcile here and nothing human to preserve — that is load_scan.py's job.
Status__c is left to its picklist default (Open) so the two loaders agree on
where a fresh finding starts.
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCAN, FINDING, DIM = "OrgIQ_Scan__c", "OrgIQ_Finding__c", "OrgIQ_Dimension_Score__c"


def sf(args, capture=True):
    proc = subprocess.run(["sf", *args, "--json"], capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if proc.returncode != 0 or payload.get("status", 1) != 0:
        sys.exit(f"sf {' '.join(args)} failed:\n{payload.get('message', proc.stderr)}")
    return payload.get("result", {})


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:      # LF for Bulk API 2.0
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def b(v):
    return "true" if v else "false"


def density_pct(ratio):
    """Semantic_Density__c is a Percent(3,1) — Salesforce stores 42.5 for 42.5%
    — while the scan JSON carries a 0..1 ratio. 99.9 is the field's ceiling, so
    a perfectly dense corpus is clamped rather than failing the whole job."""
    return min(round(float(ratio) * 100, 1), 99.9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("portfolio_json")
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--wait", default="15")
    a = ap.parse_args()
    org = a.target_org
    scans = json.loads(Path(a.portfolio_json).read_text())["scans"]
    tmp = Path(tempfile.mkdtemp(prefix="orgiq-portfolio-"))

    # uniqueness guard -----------------------------------------------------
    sids = [s["scan"]["external_scan_id"] for s in scans]
    fids = [f["external_finding_id"] for s in scans for f in s["findings"]]
    if len(set(sids)) != len(sids):
        sys.exit("duplicate external_scan_id in portfolio")
    if len(set(fids)) != len(fids):
        sys.exit(f"duplicate external_finding_id in portfolio "
                 f"({len(fids) - len(set(fids))} collisions)")

    # 1) wipe existing scans (children cascade via master-detail) ----------
    existing = sf(["data", "query", "--query", f"SELECT Id FROM {SCAN}",
                   "--target-org", org]).get("records", [])
    if existing:
        write_csv(tmp / "del.csv", ["Id"], [{"Id": r["Id"]} for r in existing])
        print(f"→ deleting {len(existing)} existing scan(s) (children cascade)…")
        sf(["data", "delete", "bulk", "--sobject", SCAN, "--file", str(tmp / "del.csv"),
            "--target-org", org, "--wait", a.wait])

    # 2) insert scans ------------------------------------------------------
    scan_cols = ["External_Scan_Id__c", "Target_Org__c", "Scan_Mode__c",
                 "Rubric_Version__c", "Composite_Score__c", "Readiness_Band__c",
                 "Components_Scanned__c", "Semantic_Density__c",
                 "Est_Grounding_Tokens__c", "Est_Remediated_Tokens__c",
                 "Gate_Applied__c", "Gate_Reason__c", "Scan_Timestamp__c"]
    write_csv(tmp / "scans.csv", scan_cols, [{
        "External_Scan_Id__c": s["scan"]["external_scan_id"],
        "Target_Org__c": s["scan"]["target_org"],
        "Scan_Mode__c": s["scan"]["scan_mode"],
        "Rubric_Version__c": s["scan"]["rubric_version"],
        "Composite_Score__c": s["scan"]["composite_score"],
        "Readiness_Band__c": s["scan"]["readiness_band"],
        "Components_Scanned__c": s["scan"]["components_scanned"],
        "Semantic_Density__c": density_pct(s["scan"]["semantic_density"]),
        "Est_Grounding_Tokens__c": s["scan"]["est_grounding_tokens"],
        "Est_Remediated_Tokens__c": s["scan"]["est_remediated_tokens"],
        "Gate_Applied__c": b(s["scan"]["gate_applied"]),
        "Gate_Reason__c": s["scan"]["gate_reason"],
        "Scan_Timestamp__c": s["scan"]["scan_timestamp"],
    } for s in scans])
    print(f"→ inserting {len(scans)} scans…")
    sf(["data", "import", "bulk", "--sobject", SCAN, "--file", str(tmp / "scans.csv"),
        "--target-org", org, "--wait", a.wait])

    # 3) map external_scan_id -> Id ---------------------------------------
    recs = sf(["data", "query", "--query",
               f"SELECT Id, External_Scan_Id__c FROM {SCAN}", "--target-org", org])["records"]
    id_of = {r["External_Scan_Id__c"]: r["Id"] for r in recs}

    # 4) insert findings ---------------------------------------------------
    # Status__c is omitted so the picklist default (Open) applies on insert,
    # matching load_scan.py — see the module docstring.
    f_cols = ["External_Finding_Id__c", "Scan__c", "Rule_Id__c", "Dimension__c",
              "Severity__c", "Confidence__c", "Component_Type__c",
              "Component_Api_Name__c", "Evidence__c", "Epic__c", "Remediation__c",
              "Acceptance_Criteria__c", "Effort_Points__c", "Blast_Radius__c",
              "Source__c", "Emits_To_Backlog__c", "Rule_Maturity__c"]
    f_rows = []
    for s in scans:
        sid = id_of[s["scan"]["external_scan_id"]]
        for f in s["findings"]:
            f_rows.append({
                "External_Finding_Id__c": f["external_finding_id"], "Scan__c": sid,
                "Rule_Id__c": f["rule_id"], "Dimension__c": f["dimension"],
                "Severity__c": f["severity"], "Confidence__c": f["confidence"],
                "Component_Type__c": f["component_type"],
                "Component_Api_Name__c": f["component_api_name"],
                "Evidence__c": f["evidence"], "Epic__c": f["epic"],
                "Remediation__c": f["remediation"],
                "Acceptance_Criteria__c": f["acceptance_criteria"],
                "Effort_Points__c": f["effort_points"], "Blast_Radius__c": f["blast_radius"],
                "Source__c": f["source"], "Emits_To_Backlog__c": b(f["emits_to_backlog"]),
                "Rule_Maturity__c": f["rule_maturity"],
            })
    write_csv(tmp / "findings.csv", f_cols, f_rows)
    print(f"→ inserting {len(f_rows)} findings…")
    sf(["data", "import", "bulk", "--sobject", FINDING, "--file", str(tmp / "findings.csv"),
        "--target-org", org, "--wait", a.wait])

    # 5) insert dimension scores ------------------------------------------
    d_cols = ["Scan__c", "Dimension__c", "Score__c", "Rule_Coverage__c",
              "In_Composite__c", "Assessment_Status__c", "Missing_Signals__c"]
    d_rows = []
    for s in scans:
        sid = id_of[s["scan"]["external_scan_id"]]
        for d in s["dimensions"]:
            d_rows.append({
                "Scan__c": sid, "Dimension__c": d["dimension"],
                "Score__c": "" if d["score"] is None else d["score"],
                "Rule_Coverage__c": d["rule_coverage"],
                "In_Composite__c": b(d["in_composite"]),
                "Assessment_Status__c": d["assessment_status"],
                "Missing_Signals__c": d["missing_signals"],
            })
    write_csv(tmp / "dims.csv", d_cols, d_rows)
    print(f"→ inserting {len(d_rows)} dimension scores…")
    sf(["data", "import", "bulk", "--sobject", DIM, "--file", str(tmp / "dims.csv"),
        "--target-org", org, "--wait", a.wait])

    print(f"\nloaded portfolio into {org}: {len(scans)} scans, "
          f"{len(f_rows)} findings, {len(d_rows)} dimension scores")


if __name__ == "__main__":
    main()
