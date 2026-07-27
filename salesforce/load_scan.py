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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scanner"))
import lifecycle  # noqa: E402  — the survival arithmetic, shared with the portfolio path

SCAN_OBJ = "OrgIQ_Scan__c"
PERSONA_OBJ = "OrgIQ_Persona__c"
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


def _annotate_survival(target_org, org, wait, tmp) -> int:
    """Recompute survival over every scan this org has, and write it back.

    Every scan is rewritten, not only the newest: a finding's run is a property
    of the sequence, so a scan arriving out of order — or a re-run that changes
    what a scan reports — moves numbers on records that were written earlier.
    """
    scans = sf(["data", "query", "--query",
                f"SELECT Id, External_Scan_Id__c, Scan_Timestamp__c FROM {SCAN_OBJ} "
                f"WHERE Target_Org__c = '{target_org.replace(chr(39), chr(92) + chr(39))}'",
                "--target-org", org]).get("records", [])
    if len(scans) < 2:
        return 0          # nothing to compare against; a run of 1 is not evidence

    rows = sf(["data", "query", "--query",
               f"SELECT Id, Scan__r.External_Scan_Id__c, Rule_Id__c, "
               f"Component_Api_Name__c, Evidence__c, Emits_To_Backlog__c "
               f"FROM {FINDING_OBJ} WHERE Scan__r.Target_Org__c = "
               f"'{target_org.replace(chr(39), chr(92) + chr(39))}'",
               "--target-org", org]).get("records", [])

    by_scan = {}
    for r in rows:
        by_scan.setdefault(r["Scan__r"]["External_Scan_Id__c"], []).append({
            "Id": r["Id"], "rule_id": r["Rule_Id__c"],
            "component_api_name": r["Component_Api_Name__c"],
            "evidence": r["Evidence__c"] or "",
            "emits_to_backlog": r["Emits_To_Backlog__c"],
        })

    shaped = [{"scan": {"external_scan_id": s["External_Scan_Id__c"],
                        "target_org": target_org,
                        "scan_timestamp": s["Scan_Timestamp__c"]},
               "findings": by_scan.get(s["External_Scan_Id__c"], [])}
              for s in scans]
    lifecycle.annotate(shaped)

    updates = [{"Id": f["Id"], "Survived_Scans__c": f.get("survived_scans", ""),
                "Resolved_In_Scan__c": f.get("resolved_in_scan", "")}
               for s in shaped for f in s["findings"]]
    if not updates:
        return 0
    _write_csv(tmp / "survival.csv",
               ["Id", "Survived_Scans__c", "Resolved_In_Scan__c"], updates)
    print(f"\u2192 recomputing survival across {len(scans)} scan(s) of this org\u2026")
    sf(["data", "update", "bulk", "--sobject", FINDING_OBJ, "--file",
        str(tmp / "survival.csv"), "--target-org", org, "--wait", wait])
    return sum(1 for s in shaped for f in s["findings"]
               if f.get("emits_to_backlog") and (f.get("survived_scans") or 0) >= 3)


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
                 "Est_Grounding_Tokens__c", "Est_Remediated_Tokens__c", "Removable_Restating__c",
                 "Removable_Duplicates__c", "Removable_Unreferenced__c",
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
        "Removable_Restating__c": (scan.get("est_removable_tokens") or {}).get("restating_descriptions", 0),
        "Removable_Duplicates__c": (scan.get("est_removable_tokens") or {}).get("duplicate_clusters", 0),
        "Removable_Unreferenced__c": (scan.get("est_removable_tokens") or {}).get("unreferenced_fields", 0),
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
              "Remediation__c", "Acceptance_Criteria__c", "Effort_Points__c", "Effort_Basis__c",
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
        "Effort_Basis__c": f.get("effort_basis", "")[:255],
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

    # 5) Replace this scan's persona surfaces -----------------------------
    #
    # Deleted and re-inserted rather than upserted: a persona that no longer
    # exists in the org has to disappear from the scan, and an upsert keyed on
    # the external id would leave it sitting there looking current.
    personas = data.get("personas", [])
    old_p = sf(["data", "query", "--query",
                f"SELECT Id FROM {PERSONA_OBJ} WHERE Scan__c='{scan_id}'",
                "--target-org", org]).get("records", [])
    if old_p:
        _write_csv(tmp / "p_del.csv", ["Id"], [{"Id": r["Id"]} for r in old_p])
        sf(["data", "delete", "bulk", "--sobject", PERSONA_OBJ, "--file",
            str(tmp / "p_del.csv"), "--target-org", org, "--wait", a.wait])
    if personas:
        p_cols = ["External_Persona_Id__c", "Scan__c", "Name", "Persona_Kind__c",
                  "Summary__c", "Unbounded__c", "Blanket_Perms__c", "Reach__c",
                  "Objects_Editable__c", "Objects_Readable__c", "Objects_Deletable__c",
                  "Fields_Visible__c", "Fields_Available__c", "Flows__c",
                  "Approvals__c", "Blocked_By__c", "Actions__c",
                  "Editable_Objects__c", "Flow_Names__c", "Blocking_Rules__c"]
        _write_csv(tmp / "personas.csv", p_cols, [{
            "External_Persona_Id__c": p["external_persona_id"], "Scan__c": scan_id,
            "Name": p["name"][:80], "Persona_Kind__c": p["persona_kind"],
            "Summary__c": p["summary"], "Unbounded__c": _b(p["unbounded"]),
            "Blanket_Perms__c": p["blanket_perms"], "Reach__c": p["reach"],
            "Objects_Editable__c": p["objects_editable"],
            "Objects_Readable__c": p["objects_readable"],
            "Objects_Deletable__c": p["objects_deletable"],
            # "" not 0: a permission set assigns no layouts, so the count is
            # unknown rather than none, and the field must hold null.
            "Fields_Visible__c": ("" if p["fields_visible"] is None
                                  else p["fields_visible"]),
            "Fields_Available__c": p["fields_available"], "Flows__c": p["flows"],
            "Approvals__c": p["approvals"], "Blocked_By__c": p["blocked_by"],
            "Actions__c": p["actions"], "Editable_Objects__c": p["editable_objects"],
            "Flow_Names__c": p["flow_names"], "Blocking_Rules__c": p["blocking_rules"],
        } for p in personas])
        print(f"\u2192 inserting {len(personas)} persona surface(s)\u2026")
        sf(["data", "import", "bulk", "--sobject", PERSONA_OBJ, "--file",
            str(tmp / "personas.csv"), "--target-org", org, "--wait", a.wait])

    # 6) Survival, from the org's own scan history -------------------------
    #
    # The one calibration input that needs nobody's cooperation: how many
    # consecutive scans have reported the same defect. The portfolio path
    # computes this in memory because it holds every scan at once; here the
    # history lives in the org, so it is read back and run through the same
    # arithmetic rather than a second implementation of it.
    stuck = _annotate_survival(scan["target_org"], org, a.wait, tmp)

    print(f"\nloaded scan {scan['external_scan_id']} into {org}: "
          f"1 scan, {len(f_rows)} findings, {len(d_rows)} dimension scores, "
          f"{len(personas)} persona surface(s), {len(moves)} status change(s)"
          + (f", {stuck} finding(s) now on their 3rd+ consecutive scan" if stuck
             else ""))


if __name__ == "__main__":
    main()
