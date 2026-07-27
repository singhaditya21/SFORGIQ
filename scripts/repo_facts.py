#!/usr/bin/env python3
"""
The counts the README states, computed from the code that makes them true.

Every number in a README rots. This one rotted badly enough to matter: it
claimed 22 rules when there were 31, 39 tests when there were 224, and a
24-org portfolio that had become two enterprises of 14 — and, worse than any
count, it said the scanner could not read an org while `scanner/org_mode.py`
was issuing real SOQL against one.

So the numbers are computed here, and `tests/test_docs.py` fails when the
README disagrees with this module. That does not stop prose going stale, but it
does stop the specific failure that already happened twice: a number that was
true when someone typed it and nobody's job to check afterwards.

    python3 scripts/repo_facts.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE_MODULES = ("orgiq_spike", "rules_ext", "external", "persona", "drift")

# A dimension code alone ("D1.") is not a rule id — the tail must be an
# UPPER_SNAKE name, or every sentence ending in "D5." would be counted.
RULE_ID = re.compile(r"\bD[1-5]\.[A-Z][A-Z0-9_]{2,}\b")


def rule_ids() -> set:
    ids = set()
    for mod in RULE_MODULES:
        ids |= set(RULE_ID.findall((ROOT / "scanner" / f"{mod}.py").read_text(encoding="utf-8")))
    return ids


def facts() -> dict:
    ids = rule_ids()
    by_dim = Counter(i.split(".")[0] for i in ids)

    objects_dir = ROOT / "salesforce/force-app/main/default/objects"
    objects = sorted(p.name for p in objects_dir.iterdir() if p.is_dir())
    fields = sum(len(list((objects_dir / o / "fields").glob("*.field-meta.xml")))
                 for o in objects)

    portfolio = json.loads((ROOT / "dashboard/public/portfolio.json").read_text(encoding="utf-8"))
    scans = portfolio["scans"]

    return {
        "rules": len(ids),
        "rules_by_dimension": {d: by_dim[d] for d in sorted(by_dim)},
        "tests": count_tests(),
        "objects": len(objects),
        "object_names": objects,
        "fields": fields,
        "scans": len(scans),
        "orgs": len({s["scan"]["targetOrg"] for s in scans}),
        "enterprises": len({s["scan"]["targetOrg"].split(" · ")[0] for s in scans}),
        "findings": sum(len(s["findings"]) for s in scans),
        "personas": sum(len(s.get("personas", [])) for s in scans),
        "tickets": sum(1 for s in scans for f in s["findings"] if f["emitsToBacklog"]),
    }


def count_tests() -> int:
    """Collected by pytest itself rather than counted with a regex: a `def
    test_` that pytest does not collect is not a test, and the README should
    say what actually runs."""
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--collect-only"],
                          capture_output=True, text=True, cwd=ROOT)
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    return int(match.group(1)) if match else 0


if __name__ == "__main__":
    print(json.dumps(facts(), indent=2))
