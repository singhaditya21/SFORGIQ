#!/usr/bin/env python3
"""
Measuring how often each rule is right.

Every finding this scanner has ever produced shipped as `experimental`, because
the maturity ladder in the schema had nothing to climb on: there was no way for
a reviewer to say "that one was wrong", and so no arithmetic waiting for them to
say it. This is the plumbing that removes both halves of that.

    python3 salesforce/precision_kit.py worksheet --target-org orgiq --out v.csv
    python3 salesforce/precision_kit.py import    --target-org orgiq --file v.csv
    python3 salesforce/precision_kit.py report    --target-org orgiq [--update-rubric]

The worksheet is stratified across rules rather than taking the top N, for the
same reason the effort worksheet is: a severity-sorted list is one or two rules
deep, and scoring those tells you nothing about the other twenty-nine. Enough of
each rule is worth far more than many of one.

`--update-rubric` writes the measured precision and the maturity it earns back
into scanner/rubric.json, which is where the scanner reads maturity from. That
is the loop closing: scoring findings is what moves a rule up the ladder, and
nothing else does.

**A caution about which loader you are using.** `load_scan.py` upserts and never
sends Verdict__c, so verdicts survive a re-scan exactly as human triage does.
`load_portfolio.py` deletes and re-inserts the whole demo portfolio — verdicts
recorded against demo findings do not survive it, and are not meant to.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scanner"))
import precision  # noqa: E402
import rubric  # noqa: E402

FINDING = "OrgIQ_Finding__c"
ID_COL = "External ID"
VERDICT_COL = "Verdict"
NOTE_COL = "Why"


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
    where = " WHERE Emits_To_Backlog__c = true"
    if a.enterprise:
        where += f" AND Scan__r.Enterprise_Id__c = '{a.enterprise}'"
    if not a.include_scored:
        where += " AND Verdict__c = null"

    rows = query(
        "SELECT External_Finding_Id__c, Rule_Id__c, Severity__c, Confidence__c, "
        "Component_Api_Name__c, Evidence__c, Scan__r.Target_Org__c FROM "
        + FINDING + where + " ORDER BY Rule_Id__c", a.target_org)
    if not rows:
        print("nothing to score — every emitted finding already has a verdict")
        return

    by_rule = defaultdict(list)
    for r in rows:
        by_rule[r["Rule_Id__c"]].append(r)

    sample = []
    for rule in sorted(by_rule):
        items = by_rule[rule]
        # Spread across the rule's own range rather than taking the first few:
        # a run of near-identical findings is one judgement repeated, not a
        # sample, and it would put a rule over the verdict floor without ever
        # having tested it on anything hard.
        step = max(1, len(items) // a.per_rule)
        sample += items[::step][:a.per_rule]

    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([ID_COL, "Rule", "Org", "Severity", "Confidence", "Component",
                    VERDICT_COL, NOTE_COL, "Evidence"])
        for r in sample:
            w.writerow([r["External_Finding_Id__c"], r["Rule_Id__c"],
                        (r.get("Scan__r") or {}).get("Target_Org__c", ""),
                        r["Severity__c"], r["Confidence__c"],
                        r["Component_Api_Name__c"], "", "",
                        (r["Evidence__c"] or "")[:200]])

    print(f"wrote {a.out}: {len(sample)} finding(s) across {len(by_rule)} rule(s)")
    print(f"\n  Put '{precision.TRUE_POSITIVE}' or '{precision.FALSE_POSITIVE}' in "
          f"'{VERDICT_COL}'.")
    print(f"  The question is only whether the finding is CORRECT. Whether it is "
          f"worth\n  fixing is a different one, and Status__c already answers it.")
    print(f"  '{NOTE_COL}' is what actually improves the rules: the precision says "
          f"which\n  rule is wrong, only the note says what it got wrong.")
    print(f"\n  Then: python3 salesforce/precision_kit.py import --target-org "
          f"{a.target_org} --file {a.out}")


# -------------------------------------------------------------- import

def cmd_import(a):
    rows = list(csv.DictReader(open(a.file, encoding="utf-8")))
    if not rows or ID_COL not in rows[0]:
        sys.exit(f"{a.file} has no '{ID_COL}' column — is it the worksheet?")

    updates, bad = [], []
    for r in rows:
        ext = (r.get(ID_COL) or "").strip()
        verdict = (r.get(VERDICT_COL) or "").strip()
        if not ext or not verdict:
            continue                       # blank is "not scored", not a verdict
        if verdict not in precision.VERDICTS:
            bad.append(f"{ext}: {verdict!r}")
            continue
        updates.append((ext, verdict, (r.get(NOTE_COL) or "").strip()))

    if bad:
        # Refused rather than skipped: a typo silently dropped is a rule whose
        # precision is computed over fewer findings than the reviewer scored.
        sys.exit(f"{len(bad)} row(s) have a verdict that is neither "
                 f"{' nor '.join(precision.VERDICTS)}:\n  " + "\n  ".join(bad[:5]))
    if not updates:
        print("nothing to import — every row left the verdict blank")
        return

    existing = {r["External_Finding_Id__c"]: r["Id"] for r in query(
        "SELECT Id, External_Finding_Id__c FROM " + FINDING, a.target_org)}
    matched = [(existing[e], v, n) for e, v, n in updates if e in existing]
    missing = [e for e, _, _ in updates if e not in existing]

    tmp = Path(tempfile.mkdtemp(prefix="orgiq-verdicts-")) / "verdicts.csv"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Id", "Verdict__c", "Verdict_Note__c"],
                           lineterminator="\n")     # Bulk API 2.0 wants LF
        w.writeheader()
        for rid, verdict, note in matched:
            w.writerow({"Id": rid, "Verdict__c": verdict, "Verdict_Note__c": note})

    sf(["data", "update", "bulk", "--sobject", FINDING, "--file", str(tmp),
        "--target-org", a.target_org, "--wait", "10"])
    print(f"imported {len(matched)} verdict(s)")
    if missing:
        print(f"  {len(missing)} id(s) matched no finding — most likely from a scan "
              f"that has since been reloaded")
    print(f"\nnow:  python3 salesforce/precision_kit.py report --target-org "
          f"{a.target_org}")


# -------------------------------------------------------------- report

MARK = {"measured": " ", "provisional": "~", "unmeasured": "·"}


def cmd_report(a):
    where = f" WHERE Scan__r.Enterprise_Id__c = '{a.enterprise}'" if a.enterprise else ""
    rows = query("SELECT Rule_Id__c, Verdict__c, Status__c FROM " + FINDING
                 + where, a.target_org)
    scores = precision.measure([{"rule_id": r["Rule_Id__c"], "verdict": r["Verdict__c"],
                                 "status": r["Status__c"]} for r in rows])

    print(f"Rule precision — {precision.summary(scores)}\n")
    print(f"  {'':1} {'rule':32} {'n':>4} {'prec':>6} {'act':>5}  maturity")
    for s in scores:
        if s.verdicts == 0 and not a.all_rules:
            continue
        prec = "—" if s.precision is None else f"{s.precision:.2f}"
        act = "—" if s.actionability is None else f"{s.actionability:.2f}"
        flag = " ← withdraw" if s.withdraw_candidate else ""
        print(f"  {MARK[s.verdict_status]} {s.rule_id:32} {s.verdicts:4} "
              f"{prec:>6} {act:>5}  {s.maturity}{flag}")

    unmeasured = [s for s in scores if s.verdict_status == "unmeasured"]
    print(f"\n  ~ under the {rubric.MIN_VERDICTS}-verdict floor, reported but not "
          f"moving the rule")
    if unmeasured:
        print(f"  · {len(unmeasured)} rule(s) with no verdicts at all — unmeasured, "
              f"which is not the same as correct")

    print("\n  prec = precision, was the finding right. act = of the right ones, the "
          "share\n  nobody suppressed. A rule can be perfectly precise and still not "
          "worth\n  shipping; only precision moves the ladder.")

    patch = precision.rubric_patch(scores)
    if not patch:
        print(f"\nNothing has cleared the {rubric.MIN_VERDICTS}-verdict floor yet, "
              f"which is the\nhonest state. The worksheet subcommand produces "
              f"something a reviewer can\nscore in an afternoon.")
        return

    if a.update_rubric:
        path = ROOT / "scanner/rubric.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("validation", {})["measured"] = patch
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"\nwrote {len(patch)} measured rule(s) into scanner/rubric.json — "
              f"the next scan\nstamps each finding with the maturity its rule has "
              f"earned.")
    else:
        print(f"\n{len(patch)} rule(s) have cleared the floor. Re-run with "
              f"--update-rubric to\nwrite them into scanner/rubric.json, which is "
              f"where the scanner reads\nmaturity from.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worksheet", help="emit a stratified sample to score")
    w.add_argument("--target-org", required=True)
    w.add_argument("--out", default="precision-worksheet.csv")
    w.add_argument("--per-rule", type=int, default=12)
    w.add_argument("--enterprise", default="")
    w.add_argument("--include-scored", action="store_true",
                   help="re-sample findings that already carry a verdict")
    w.set_defaults(fn=cmd_worksheet)

    i = sub.add_parser("import", help="read scored verdicts back in")
    i.add_argument("--target-org", required=True)
    i.add_argument("--file", required=True)
    i.set_defaults(fn=cmd_import)

    r = sub.add_parser("report", help="per-rule precision and earned maturity")
    r.add_argument("--target-org", required=True)
    r.add_argument("--enterprise", default="")
    r.add_argument("--all-rules", action="store_true",
                   help="include rules with no verdicts at all")
    r.add_argument("--update-rubric", action="store_true")
    r.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
