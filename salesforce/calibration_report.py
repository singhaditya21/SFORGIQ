#!/usr/bin/env python3
"""
Report how well the effort model matches what remediation actually took.

    python3 salesforce/calibration_report.py --target-org orgiq

Reads Actual_Effort_Points__c off findings someone has finished and written up,
compares each against the estimate that was given, and says whether the model
should move. With no actuals recorded it says exactly that — which is the true
state today, and the reason effort is still labelled provisional everywhere it
appears.

This is the loop that closes the PRD's own risk-register entry: effort estimates
carry the value claim and are uncalibrated. They stay uncalibrated until real
engagements are recorded here; what changes is that there is now somewhere to
record them and a number that says how far off the model is.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scanner"))
import effort  # noqa: E402


def query(soql, org):
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
    a = ap.parse_args()

    rows = query(
        "SELECT Rule_Id__c, Effort_Points__c, Actual_Effort_Points__c, Effort_Basis__c "
        "FROM OrgIQ_Finding__c WHERE Actual_Effort_Points__c != null", a.target_org)

    cal = effort.calibrate([{
        "rule_id": r["Rule_Id__c"],
        "effort_points": r["Effort_Points__c"],
        "actual_effort": r["Actual_Effort_Points__c"],
    } for r in rows])

    total = query("SELECT COUNT() FROM OrgIQ_Finding__c", a.target_org)
    print(f"Effort model: {effort.MODEL_VERSION}")
    print(f"  {cal.verdict}")
    if not cal.samples:
        print(f"\n  Nothing to compare against yet. Record what a fix actually took in\n"
              f"  Actual_Effort_Points__c on the finding, and re-run this. Until then\n"
              f"  every estimate is judgement adjusted by measured evidence, and is\n"
              f"  labelled provisional wherever it is shown.")
        return

    print(f"  median actual/estimate : {cal.median_ratio}")
    print(f"  mean                   : {cal.mean_ratio}")
    print(f"  within one scale stop  : {cal.within_half_band:.0%}")
    print("\n  by rule:")
    for rule, acc in sorted(cal.by_rule.items(), key=lambda kv: -kv[1]["n"]):
        print(f"    {rule:32} n={acc['n']:<4} ratio={acc['ratio']}")


if __name__ == "__main__":
    main()
