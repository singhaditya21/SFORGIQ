#!/usr/bin/env python3
"""
Getting real numbers into the effort model.

"Engagement data cannot come from code" is true and is not an answer. The data
does not exist yet because there is nowhere for it to land and no one is going to
hand-edit a Salesforce field — so this is the plumbing that removes both excuses.

Three sources, deliberately kept apart, because they are not equally good:

  actual     what a fix really took. The only thing that calibrates anything.
             Arrives from wherever the work is actually tracked — a Jira export,
             a spreadsheet — matched on the External ID the backlog CSV already
             carries. Nobody types into Salesforce.

  expert     what a practitioner says a fix will take, before anyone does it.
             Legitimate — expert elicitation is how you calibrate when outcomes
             do not exist yet — but it is judgement checking judgement, so it
             lives in its own field and never counts as an actual. Available
             this week, from anyone who has done the work.

  survival   how many scans a finding lived through. Observable from data
             already held, requires nobody's cooperation, and is NOT effort. It
             says what is not getting fixed, which is a different and also useful
             thing.

    python3 salesforce/calibration_kit.py worksheet --target-org orgiq --out w.csv
    python3 salesforce/calibration_kit.py import --target-org orgiq --file w.csv
    python3 salesforce/calibration_kit.py report --target-org orgiq
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scanner"))
import effort  # noqa: E402

FINDING = "OrgIQ_Finding__c"

# What the worksheet asks for and the importer reads back. External ID is the
# join: it is already on every row of the backlog CSV, so a Jira export that
# kept the column round-trips without anyone mapping anything.
ID_COL = "External ID"
ACTUAL_COL = "Actual Points"
EXPERT_COL = "Expert Points"


def sf(args):
    proc = subprocess.run(["sf", *args, "--json"], capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if proc.returncode != 0 or payload.get("status", 1) != 0:
        sys.exit(f"sf {' '.join(args)} failed:\n{payload.get('message', proc.stderr)}")
    return payload.get("result", {})


def query(soql, org):
    return sf(["data", "query", "--query", soql, "--target-org", org]).get("records", [])


# ----------------------------------------------------------- worksheet

def cmd_worksheet(a):
    """Emit a stratified sample for a practitioner to estimate.

    Stratified, not the top N: the top of a severity-sorted list is all one or
    two rules, and calibrating those tells you nothing about the other twenty.
    A few of each rule is worth far more than many of one.
    """
    rows = query(
        "SELECT External_Finding_Id__c, Rule_Id__c, Severity__c, Component_Api_Name__c, "
        "Evidence__c, Effort_Points__c, Blast_Radius__c FROM " + FINDING +
        " WHERE Emits_To_Backlog__c = true ORDER BY Rule_Id__c", a.target_org)

    by_rule = defaultdict(list)
    for r in rows:
        by_rule[r["Rule_Id__c"]].append(r)

    sample = []
    for rule in sorted(by_rule):
        # Spread across the rule's own range rather than taking the first few,
        # so the sample carries its easy and hard ends, not one cluster.
        items = sorted(by_rule[rule], key=lambda r: (r["Blast_Radius__c"] or 0))
        step = max(1, len(items) // a.per_rule)
        sample += items[::step][:a.per_rule]

    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([ID_COL, "Rule", "Severity", "Component", "Dependants",
                    "Our Estimate", EXPERT_COL, ACTUAL_COL, "Evidence"])
        for r in sample:
            w.writerow([r["External_Finding_Id__c"], r["Rule_Id__c"], r["Severity__c"],
                        r["Component_Api_Name__c"], r["Blast_Radius__c"] or 0,
                        r["Effort_Points__c"], "", "", (r["Evidence__c"] or "")[:180]])

    print(f"wrote {a.out}: {len(sample)} finding(s) across {len(by_rule)} rule(s)")
    print(f"  Fill in '{EXPERT_COL}' (what you think it takes) or '{ACTUAL_COL}' "
          f"(what it took), then:")
    print(f"    python3 salesforce/calibration_kit.py import --target-org {a.target_org} "
          f"--file {a.out}")
    print(f"  'Our Estimate' is deliberately shown — hiding it would get a cleaner\n"
          f"  number and a less useful one, because the disagreements are the point.")


# -------------------------------------------------------------- import

def cmd_import(a):
    """Read actuals and/or expert estimates back in, matched on External ID."""
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    if not rows or ID_COL not in rows[0]:
        sys.exit(f"{a.file} has no '{ID_COL}' column — is it the worksheet, or a "
                 f"backlog export that kept it?")

    updates = []
    for r in rows:
        ext = (r.get(ID_COL) or "").strip()
        if not ext:
            continue
        actual = (r.get(ACTUAL_COL) or "").strip()
        expert = (r.get(EXPERT_COL) or "").strip()
        if not actual and not expert:
            continue                       # blank is "not answered", not zero
        updates.append((ext, actual, expert))

    if not updates:
        print("nothing to import — every row left both columns blank")
        return

    existing = {r["External_Finding_Id__c"]: r["Id"] for r in query(
        "SELECT Id, External_Finding_Id__c FROM " + FINDING, a.target_org)}
    matched = [(existing[e], act, exp) for e, act, exp in updates if e in existing]
    missing = [e for e, _, _ in updates if e not in existing]

    tmp = Path(tempfile.mkdtemp(prefix="orgiq-cal-")) / "actuals.csv"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Id", "Actual_Effort_Points__c",
                                           "Expert_Estimate_Points__c"],
                           lineterminator="\n")     # Bulk API 2.0 wants LF
        w.writeheader()
        for rid, act, exp in matched:
            w.writerow({"Id": rid, "Actual_Effort_Points__c": act,
                        "Expert_Estimate_Points__c": exp})

    sf(["data", "update", "bulk", "--sobject", FINDING, "--file", str(tmp),
        "--target-org", a.target_org, "--wait", "10"])
    print(f"imported {len(matched)} row(s)")
    if missing:
        print(f"  {len(missing)} id(s) matched no finding — most likely from an older "
              f"scan, since a finding id is scoped to the scan that produced it")
    print("\nnow:  python3 salesforce/calibration_kit.py report --target-org "
          + a.target_org)


# -------------------------------------------------------------- report

def cmd_report(a):
    actuals = query(
        "SELECT Rule_Id__c, Effort_Points__c, Actual_Effort_Points__c FROM " + FINDING +
        " WHERE Actual_Effort_Points__c != null", a.target_org)
    experts = query(
        "SELECT Rule_Id__c, Effort_Points__c, Expert_Estimate_Points__c FROM " + FINDING +
        " WHERE Expert_Estimate_Points__c != null", a.target_org)

    print(f"Effort model: {effort.MODEL_VERSION}\n")

    cal = effort.calibrate([{"rule_id": r["Rule_Id__c"],
                             "effort_points": r["Effort_Points__c"],
                             "actual_effort": r["Actual_Effort_Points__c"]}
                            for r in actuals])
    print("MEASURED (what fixes actually took)")
    print(f"  {cal.verdict}")
    if cal.samples:
        print(f"  median actual/estimate {cal.median_ratio} · "
              f"within one scale stop {cal.within_half_band:.0%}")

    exp = effort.calibrate([{"rule_id": r["Rule_Id__c"],
                             "effort_points": r["Effort_Points__c"],
                             "actual_effort": r["Expert_Estimate_Points__c"]}
                            for r in experts])
    print("\nELICITED (what a practitioner expects — judgement, not measurement)")
    if not exp.samples:
        print("  no expert estimates recorded")
    else:
        print(f"  {exp.samples} estimate(s) · median expert/model {exp.median_ratio}")
        worst = sorted(exp.by_rule.items(),
                       key=lambda kv: -abs(1 - kv[1]["ratio"]))[:5]
        print("  rules the practitioner disagrees with most:")
        for rule, acc in worst:
            arrow = "higher" if acc["ratio"] > 1 else "lower"
            print(f"    {rule:32} n={acc['n']:<3} they say {acc['ratio']}x {arrow}")

    if not cal.samples and not exp.samples:
        print("\nNeither source has any data yet, which is the honest state. The "
              "\nworksheet subcommand produces something a practitioner can fill in "
              "\nin an afternoon — that is the cheapest way to stop guessing.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worksheet", help="emit a stratified sample to estimate")
    w.add_argument("--target-org", required=True)
    w.add_argument("--out", default="calibration-worksheet.csv")
    w.add_argument("--per-rule", type=int, default=5)
    w.set_defaults(fn=cmd_worksheet)

    i = sub.add_parser("import", help="read actuals / expert estimates back in")
    i.add_argument("--target-org", required=True)
    i.add_argument("--file", required=True)
    i.set_defaults(fn=cmd_import)

    r = sub.add_parser("report", help="where the model stands")
    r.add_argument("--target-org", required=True)
    r.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
