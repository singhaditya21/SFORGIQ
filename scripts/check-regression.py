#!/usr/bin/env python3
"""
Compare each org's newest scan against its previous one, from the findings org.

    python3 scripts/check-regression.py --target-org orgiq
    python3 scripts/check-regression.py --target-org orgiq --fail-on-regression

Exits non-zero with `--fail-on-regression`, which is what makes the scheduled
workflow a gate rather than a newsletter. Without it, it reports and exits 0 —
useful when you want the summary in a log without breaking a build.

The comparison itself lives in `scanner/regression.py` and is unit-tested there.
This file is only the part that needs an org: pulling the scans out.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scanner"))
import regression  # noqa: E402

SCAN = "OrgIQ_Scan__c"
FINDING = "OrgIQ_Finding__c"


def query(soql, org):
    proc = subprocess.run(["sf", "data", "query", "--query", soql,
                           "--target-org", org, "--json"],
                          capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if payload.get("status", 1) != 0:
        sys.exit(f"query failed: {payload.get('message', proc.stderr)}")
    return payload["result"]["records"]


def load(org, enterprise=None):
    """Every scan, with its findings, shaped the way regression.py expects.

    Scoped to one tenant when asked. A portfolio-wide run in a multi-tenant
    install would compare orgs correctly — they are grouped by name — but would
    put another enterprise's regressions in this one's report.
    """
    where = f" WHERE Enterprise_Id__c = '{enterprise}'" if enterprise else ""
    scans = query(
        "SELECT External_Scan_Id__c, Target_Org__c, Composite_Score__c, "
        f"Scan_Timestamp__c FROM {SCAN}{where}", org)
    if not scans:
        return []

    ids = {s["External_Scan_Id__c"] for s in scans}
    findings = query(
        "SELECT Scan__r.External_Scan_Id__c, Rule_Id__c, Component_Api_Name__c, "
        f"Severity__c, Resolved_In_Scan__c FROM {FINDING}"
        + (f" WHERE Scan__r.Enterprise_Id__c = '{enterprise}'" if enterprise else ""),
        org)

    by_scan = {}
    for f in findings:
        sid = (f.get("Scan__r") or {}).get("External_Scan_Id__c")
        if sid in ids:
            by_scan.setdefault(sid, []).append({
                "rule_id": f["Rule_Id__c"],
                "component_api_name": f["Component_Api_Name__c"],
                "severity": f["Severity__c"],
                "resolved_in_scan": f["Resolved_In_Scan__c"] or "",
            })

    return [{"scan": {"target_org": s["Target_Org__c"],
                      "composite_score": int(s["Composite_Score__c"] or 0),
                      "scan_timestamp": s["Scan_Timestamp__c"]},
             "findings": by_scan.get(s["External_Scan_Id__c"], [])}
            for s in scans]


ARROW = {"regressed": "▼", "improved": "▲", "unchanged": "=", "no-history": "·"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--enterprise", default="",
                    help="tenant id to scope to; omit to cover every tenant")
    ap.add_argument("--tolerance", type=int, default=regression.DEFAULT_TOLERANCE)
    ap.add_argument("--fail-on-regression", action="store_true")
    a = ap.parse_args()

    scans = load(a.target_org, a.enterprise or None)
    if not scans:
        print("no scans found — nothing to compare")
        return 0

    verdicts = regression.compare_portfolio(scans, a.tolerance)
    print(f"Readiness since the previous scan  ({regression.summary(verdicts)})\n")
    for v in verdicts:
        delta = "" if v.delta is None else f"{v.delta:+d}"
        score = "—" if v.score_after is None else str(v.score_after)
        print(f"  {ARROW[v.status]} {v.org:36} {score:>3} {delta:>4}")
        for r in v.reasons:
            print(f"      {r}")

    regressed = [v for v in verdicts if v.regressed]
    if regressed and a.fail_on_regression:
        print(f"\n{len(regressed)} org(s) regressed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
