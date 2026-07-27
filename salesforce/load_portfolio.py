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
PERSONA = "OrgIQ_Persona__c"
TARGET_ORG = "OrgIQ_Target_Org__c"
ENTERPRISE = "OrgIQ_Enterprise__c"


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

    # 1a) upsert the tenants ----------------------------------------------
    # First, and before the orgs: Target_Org.Enterprise__c is a master-detail, so
    # an org literally cannot be created outside an enterprise. That is the
    # point — the boundary is the platform's, not a filter the query layer has
    # to remember.
    tenants = {}
    for s in scans:
        e = s.get("enterprise")
        if e:
            tenants[e["external_enterprise_id"]] = e
    ent_id_by_ext = {}
    if tenants:
        ent_cols = ["External_Enterprise_Id__c", "Name", "Industry__c", "Notes__c"]
        write_csv(tmp / "enterprises.csv", ent_cols, [{
            "External_Enterprise_Id__c": e["external_enterprise_id"],
            "Name": e["name"][:80],
            "Industry__c": e.get("industry", ""),
            "Notes__c": e.get("notes", ""),
        } for e in tenants.values()])
        print(f"\u2192 upserting {len(tenants)} enterprise(s)\u2026")
        sf(["data", "upsert", "bulk", "--sobject", ENTERPRISE, "--file",
            str(tmp / "enterprises.csv"), "--external-id", "External_Enterprise_Id__c",
            "--target-org", org, "--wait", a.wait])
        for r in sf(["data", "query", "--query",
                     f"SELECT Id, External_Enterprise_Id__c FROM {ENTERPRISE}",
                     "--target-org", org])["records"]:
            ent_id_by_ext[r["External_Enterprise_Id__c"]] = r["Id"]

    # 1b) upsert the orgs the scans belong to ------------------------------
    # Upserted, not wiped: an org outlives any one scan of it, and its type,
    # refresh date and notes are the context every scan is read against.
    orgs = {}
    for s in scans:
        o = s.get("org")
        if o:
            orgs[o["external_org_id"]] = o
    org_id_by_ext = {}
    if orgs:
        org_cols = ["External_Org_Id__c", "Enterprise__c", "Name", "Org_Type__c",
                    "Is_Production__c", "Instance_Url__c", "Last_Refreshed__c",
                    "Notes__c"]
        write_csv(tmp / "orgs.csv", org_cols, [{
            "External_Org_Id__c": o["external_org_id"],
            "Enterprise__c": ent_id_by_ext.get(o.get("enterprise_id"), ""),
            "Name": o["name"][:80],
            "Org_Type__c": o["org_type"],
            "Is_Production__c": b(o["is_production"]),
            "Instance_Url__c": o.get("instance_url") or "",
            "Last_Refreshed__c": o.get("last_refreshed") or "",
            "Notes__c": o.get("notes") or "",
        } for o in orgs.values()])
        print(f"→ upserting {len(orgs)} target org(s)…")
        sf(["data", "upsert", "bulk", "--sobject", TARGET_ORG, "--file", str(tmp / "orgs.csv"),
            "--external-id", "External_Org_Id__c", "--target-org", org, "--wait", a.wait])
        for r in sf(["data", "query", "--query",
                     f"SELECT Id, External_Org_Id__c FROM {TARGET_ORG}",
                     "--target-org", org])["records"]:
            org_id_by_ext[r["External_Org_Id__c"]] = r["Id"]

    # 2) insert scans ------------------------------------------------------
    scan_cols = ["External_Scan_Id__c", "Enterprise_Id__c", "Target_Org__c",
                 "Target_Org_Ref__c", "Scan_Mode__c",
                 "Rubric_Version__c", "Composite_Score__c", "Readiness_Band__c",
                 "Components_Scanned__c", "Semantic_Density__c",
                 "Est_Grounding_Tokens__c", "Est_Remediated_Tokens__c", "Removable_Restating__c",
                 "Removable_Duplicates__c", "Removable_Unreferenced__c",
                 "Gate_Applied__c", "Gate_Reason__c", "Scan_Timestamp__c"]
    write_csv(tmp / "scans.csv", scan_cols, [{
        "External_Scan_Id__c": s["scan"]["external_scan_id"],
        # Denormalised: the master-detail chain runs out of levels before it
        # reaches the scan, so this is what every read path scopes on.
        "Enterprise_Id__c": s["scan"].get("enterprise_id", ""),
        "Target_Org__c": s["scan"]["target_org"],
        "Target_Org_Ref__c": org_id_by_ext.get(s["scan"].get("target_org_external_id"), ""),
        "Scan_Mode__c": s["scan"]["scan_mode"],
        "Rubric_Version__c": s["scan"]["rubric_version"],
        "Composite_Score__c": s["scan"]["composite_score"],
        "Readiness_Band__c": s["scan"]["readiness_band"],
        "Components_Scanned__c": s["scan"]["components_scanned"],
        "Semantic_Density__c": density_pct(s["scan"]["semantic_density"]),
        "Est_Grounding_Tokens__c": s["scan"]["est_grounding_tokens"],
        "Est_Remediated_Tokens__c": s["scan"]["est_remediated_tokens"],
        "Removable_Restating__c": (s["scan"].get("est_removable_tokens") or {}).get("restating_descriptions", 0),
        "Removable_Duplicates__c": (s["scan"].get("est_removable_tokens") or {}).get("duplicate_clusters", 0),
        "Removable_Unreferenced__c": (s["scan"].get("est_removable_tokens") or {}).get("unreferenced_fields", 0),
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
              "Acceptance_Criteria__c", "Effort_Points__c", "Effort_Basis__c", "Blast_Radius__c",
              "Source__c", "Emits_To_Backlog__c", "Rule_Maturity__c",
              "Survived_Scans__c", "Resolved_In_Scan__c"]
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
                "Effort_Basis__c": f.get("effort_basis", "")[:255],
                "Source__c": f["source"], "Emits_To_Backlog__c": b(f["emits_to_backlog"]),
                "Rule_Maturity__c": f["rule_maturity"],
                # Blank, not 0, when the scan history could not establish a run —
                # "not measured" and "seen once" must not render alike.
                "Survived_Scans__c": f.get("survived_scans", ""),
                "Resolved_In_Scan__c": f.get("resolved_in_scan", ""),
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

    # 6) insert persona surfaces ------------------------------------------
    # Not findings. A finding says something is wrong; a surface says what a
    # persona can do, and most of them are correct — which is the half of the
    # permission question a backlog of problems can never answer.
    p_cols = ["External_Persona_Id__c", "Scan__c", "Name", "Persona_Kind__c",
              "Summary__c", "Unbounded__c", "Blanket_Perms__c", "Reach__c",
              "Objects_Editable__c", "Objects_Readable__c", "Objects_Deletable__c",
              "Fields_Visible__c", "Fields_Available__c", "Flows__c", "Approvals__c",
              "Blocked_By__c", "Actions__c", "Editable_Objects__c", "Flow_Names__c",
              "Blocking_Rules__c"]
    p_rows = []
    for s in scans:
        sid = id_of[s["scan"]["external_scan_id"]]
        for p in s.get("personas", []):
            p_rows.append({
                "External_Persona_Id__c": p["external_persona_id"], "Scan__c": sid,
                "Name": p["name"][:80], "Persona_Kind__c": p["persona_kind"],
                "Summary__c": p["summary"], "Unbounded__c": b(p["unbounded"]),
                "Blanket_Perms__c": p["blanket_perms"], "Reach__c": p["reach"],
                "Objects_Editable__c": p["objects_editable"],
                "Objects_Readable__c": p["objects_readable"],
                "Objects_Deletable__c": p["objects_deletable"],
                # "" for a permission set: it assigns no layouts, so the count is
                # unknown rather than zero, and Salesforce must hold null not 0.
                "Fields_Visible__c": ("" if p["fields_visible"] is None
                                      else p["fields_visible"]),
                "Fields_Available__c": p["fields_available"],
                "Flows__c": p["flows"], "Approvals__c": p["approvals"],
                "Blocked_By__c": p["blocked_by"], "Actions__c": p["actions"],
                "Editable_Objects__c": p["editable_objects"],
                "Flow_Names__c": p["flow_names"],
                "Blocking_Rules__c": p["blocking_rules"],
            })
    if p_rows:
        write_csv(tmp / "personas.csv", p_cols, p_rows)
        print(f"\u2192 inserting {len(p_rows)} persona surfaces\u2026")
        sf(["data", "import", "bulk", "--sobject", PERSONA, "--file",
            str(tmp / "personas.csv"), "--target-org", org, "--wait", a.wait])

    print(f"\nloaded portfolio into {org}: {len(scans)} scans, "
          f"{len(f_rows)} findings, {len(d_rows)} dimension scores, "
          f"{len(p_rows)} persona surfaces")


if __name__ == "__main__":
    main()
