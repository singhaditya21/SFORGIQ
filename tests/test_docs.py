"""The README's numbers, and the demo/live shape parity.

Two things here, both defending against the same failure: something that was
true when it was written and became false with nobody's job to notice.

The README claimed 22 rules when there were 31 and 39 tests when there were
224, and — far worse than any count — said the scanner could not read an org
while `scanner/org_mode.py` was issuing real SOQL against one. Prose still has
to be written by hand; counts do not.

Live mode and demo mode both have to produce the same shape, and only demo mode
is ever exercised without a Salesforce login. When `OrgIQ_Persona__c` was added,
live mode was not updated and would have rendered *less* against a real org than
against the bundled file. That was caught by a script needing org auth, so CI
could never have caught it — hence a static check here.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repo_facts                                             # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")
LIVE_JS = (ROOT / "dashboard/src/lib/live.js").read_text(encoding="utf-8")


# ------------------------------------------------------------ README counts

def stated(pattern) -> int:
    """A number the README states, as an int. Commas allowed — the file writes
    1,365 and the code counts 1365."""
    m = re.search(pattern, README)
    assert m, f"README no longer states this at all: {pattern}"
    return int(m.group(1).replace(",", ""))


def test_the_readme_states_the_rule_count_the_scanner_has():
    assert stated(r"\*\*(\d+) rules\*\*") == repo_facts.facts()["rules"]


def test_the_readme_states_the_number_of_tests_that_run():
    """Counted by pytest's own collection, so a `def test_` it does not collect
    cannot inflate the figure."""
    assert stated(r"\*\*(\d+) pytest tests\*\*") == repo_facts.facts()["tests"]


def test_the_readme_states_the_objects_and_fields_that_exist():
    f = repo_facts.facts()
    assert stated(r"\*\*(\d+) objects, \d+ fields\*\*") == f["objects"]
    assert stated(r"\*\*\d+ objects, (\d+) fields\*\*") == f["fields"]


def test_the_readme_states_the_portfolio_that_is_actually_bundled():
    f = repo_facts.facts()
    for label, key in (("enterprises", "enterprises"), ("orgs", "orgs"),
                       ("scans", "scans"), ("findings", "findings"),
                       ("persona surfaces", "personas")):
        assert stated(r"([\d,]+) " + label) == f[key], label


def test_the_readme_does_not_still_say_source_mode_is_the_only_mode():
    """The single most misleading sentence this file has carried: it told a
    reader the product could not do the thing `scanner/org_mode.py` does."""
    for claim in ("Source mode is the only mode",
                  "`--mode` is a label, not a connection",
                  "No code path in this repository reads a *target* org"):
        assert claim not in README, f"README still claims: {claim}"


# -------------------------------------------------- demo / live shape parity

def test_live_mode_queries_every_object_the_demo_export_carries():
    """Demo mode is exported from the org by dashboard/export_portfolio.py and
    live mode queries the org directly. If they disagree about which objects to
    read, connecting a real org shows less than the bundled file."""
    exporter = (ROOT / "dashboard/export_portfolio.py").read_text(encoding="utf-8")
    objects = set(re.findall(r"FROM (OrgIQ_\w+__c)", exporter))
    missing = sorted(o for o in objects if o not in LIVE_JS)
    assert not missing, f"live mode never queries: {missing}"


def test_live_mode_reads_every_field_the_demo_export_reads():
    """Field-level, not just object-level: the persona regression was an object,
    but Survived_Scans__c was a field on an object live mode already queried,
    and only this check would have caught it."""
    exporter = (ROOT / "dashboard/export_portfolio.py").read_text(encoding="utf-8")
    # Both files build their SOQL by concatenating string literals across lines,
    # so the field names are matched directly rather than by splitting on commas
    # — a split picks up the quotes and newlines between literals.
    wanted = set()
    for block, _obj in re.findall(r'"SELECT (.+?)FROM (OrgIQ_\w+__c)', exporter, re.S):
        wanted |= set(re.findall(r"\b\w+__c\b", block))
    missing = sorted(f for f in wanted if f not in LIVE_JS)
    assert not missing, f"live mode does not read: {missing}"


def test_the_bundled_portfolio_carries_the_personas_it_claims_to():
    """A guard on the export itself: portfolio.json is committed, so an export
    run before personas existed would ship silently."""
    data = json.loads((ROOT / "dashboard/public/portfolio.json").read_text(encoding="utf-8"))
    assert all("personas" in s for s in data["scans"])
    assert sum(len(s["personas"]) for s in data["scans"]) > 0
