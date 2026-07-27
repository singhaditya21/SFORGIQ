"""Regression detection between two scans of one org.

The line these defend: a regression is reported when something actually got
worse, and silence means "compared and found nothing", never "did not look".
"""

import regression


def scan(org, score, findings=(), ts="2026-01-01T00:00:00"):
    return {"scan": {"target_org": org, "composite_score": score, "scan_timestamp": ts},
            "findings": list(findings)}


def f(rule="D1.X", component="A__c", severity="Medium", resolved=None):
    row = {"rule_id": rule, "component_api_name": component, "severity": severity}
    if resolved:
        row["resolved_in_scan"] = resolved
    return row


# ------------------------------------------------------------- the score

def test_a_score_that_falls_past_the_tolerance_is_a_regression():
    v = regression.compare(scan("Org", 70), scan("Org", 55))
    assert v.regressed and v.delta == -15
    assert "composite fell 70 to 55" in v.reasons[0]


def test_a_move_inside_the_tolerance_is_not_reported():
    """These scores are provisional. A one-point move is noise, and reporting it
    trains everyone to ignore the check."""
    assert not regression.compare(scan("Org", 70), scan("Org", 68)).regressed


def test_a_slow_slide_still_shows_up_every_scan():
    """Each drop is measured against the previous scan, so three consecutive
    two-point falls are three comparisons — not one that averages them away."""
    v = regression.compare(scan("Org", 70), scan("Org", 60), tolerance=5)
    assert v.regressed


def test_a_rising_score_is_reported_as_improved_not_merely_not_regressed():
    v = regression.compare(scan("Org", 55), scan("Org", 70))
    assert v.status == "improved" and v.delta == 15


def test_an_unchanged_score_is_its_own_verdict():
    assert regression.compare(scan("Org", 70), scan("Org", 70)).status == "unchanged"


# ---------------------------------------------------------- new Criticals

def test_a_new_critical_regresses_even_when_the_score_barely_moves():
    """A Critical D4 finding caps the composite at 60 on its own (PRD §4.2), so
    an org can acquire one while the number hardly moves. Watching only the
    score would miss the finding that matters most."""
    before = scan("Org", 62)
    after = scan("Org", 60, [f("D4.PERSONA_UNBOUNDED", "Agent", "Critical")])
    v = regression.compare(before, after)
    assert v.regressed
    assert "new Critical" in " ".join(v.reasons)


def test_a_critical_that_was_already_there_is_not_new():
    """Otherwise every scan of an org with a standing Critical fails, and the
    check becomes something to switch off."""
    crit = [f("D4.PERSONA_UNBOUNDED", "Agent", "Critical")]
    assert not regression.compare(scan("Org", 60, crit), scan("Org", 60, crit)).regressed


# ------------------------------------------------------ returning defects

def test_a_finding_that_was_resolved_and_came_back_is_a_regression():
    """Different, and worse, than one never fixed: something undid the work."""
    before = scan("Org", 70, [f("D1.X", "A__c", resolved="SCAN-2")])
    after = scan("Org", 70, [f("D1.X", "A__c")])
    v = regression.compare(before, after)
    assert v.regressed
    assert "returned" in " ".join(v.reasons)


def test_a_brand_new_finding_is_not_treated_as_a_return():
    before = scan("Org", 70)
    after = scan("Org", 70, [f("D1.X", "A__c")])
    assert not regression.compare(before, after).regressed


# ------------------------------------------------------------- no history

def test_a_first_scan_is_not_a_regression_and_says_so():
    """"Nothing to compare against" and "compared, found nothing" must not read
    alike — the first is a gap in the data, the second is a result."""
    v = regression.compare(None, scan("Org", 40))
    assert v.status == "no-history" and not v.regressed
    assert "nothing to compare" in v.reasons[0]


# -------------------------------------------------------------- portfolio

def test_each_org_is_compared_only_against_itself():
    """A comparison spanning two orgs would report a regression neither had."""
    scans = [scan("A", 80, ts="2026-01-01T00:00:00"),
             scan("A", 40, ts="2026-04-01T00:00:00"),
             scan("B", 40, ts="2026-01-01T00:00:00"),
             scan("B", 80, ts="2026-04-01T00:00:00")]
    verdicts = {v.org: v for v in regression.compare_portfolio(scans)}
    assert verdicts["A"].status == "regressed"
    assert verdicts["B"].status == "improved"


def test_scans_are_ordered_by_timestamp_not_by_arrival():
    """A portfolio builds history after the current scan, so the list is not
    chronological — comparing in list order would invert every verdict."""
    scans = [scan("A", 40, ts="2026-04-01T00:00:00"),
             scan("A", 80, ts="2026-01-01T00:00:00")]
    assert regression.compare_portfolio(scans)[0].status == "regressed"


def test_regressions_sort_first():
    """The output is read top-down by someone who wants to know whether to act."""
    scans = [scan("Good", 50, ts="2026-01-01T00:00:00"),
             scan("Good", 90, ts="2026-04-01T00:00:00"),
             scan("Bad", 90, ts="2026-01-01T00:00:00"),
             scan("Bad", 50, ts="2026-04-01T00:00:00")]
    assert regression.compare_portfolio(scans)[0].org == "Bad"
