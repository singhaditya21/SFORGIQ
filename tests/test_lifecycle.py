"""Survival: how long a finding has been there.

The line these defend: survival is elapsed evidence and is never allowed to
become an effort claim, and a run only ever counts scans that actually reported
the defect one after another.
"""

import lifecycle


def scan(sid, org, ts, findings):
    return {"scan": {"external_scan_id": sid, "target_org": org, "scan_timestamp": ts},
            "findings": findings}


def f(rule, component, evidence="", emits=True, points=3):
    return {"rule_id": rule, "component_api_name": component, "evidence": evidence,
            "emits_to_backlog": emits, "effort_points": points}


def runs(scans):
    return {(x["rule_id"], x["component_api_name"]): x.get("survived_scans")
            for s in scans for x in s["findings"]}


# ------------------------------------------------------------- counting

def test_a_finding_seen_in_three_consecutive_scans_has_survived_three():
    scans = [scan(f"S{i}", "Org", f"2026-0{i}-01T00:00:00", [f("R", "A__c")])
             for i in (1, 2, 3)]
    lifecycle.annotate(scans)
    assert [x["findings"][0]["survived_scans"] for x in scans] == [1, 2, 3]


def test_scans_are_ordered_by_date_not_by_the_order_they_arrive_in():
    """A portfolio builds history after the current scan, so the list is not
    chronological. Counting in list order would report the newest scan as the
    first sighting and invert every run."""
    a = scan("S3", "Org", "2026-03-01T00:00:00", [f("R", "A__c")])
    b = scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c")])
    lifecycle.annotate([a, b])
    assert b["findings"][0]["survived_scans"] == 1
    assert a["findings"][0]["survived_scans"] == 2


def test_a_gap_restarts_the_run_rather_than_extending_it():
    """A defect fixed, regressed and now back has been present for one scan, not
    three. The other reading turns a burn-down that went backwards into steady
    neglect, which is a different problem with a different owner."""
    scans = [scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c")]),
             scan("S2", "Org", "2026-02-01T00:00:00", []),
             scan("S3", "Org", "2026-03-01T00:00:00", [f("R", "A__c")])]
    lifecycle.annotate(scans)
    assert scans[2]["findings"][0]["survived_scans"] == 1


def test_two_orgs_with_the_same_defect_do_not_share_a_run():
    """Survival is a statement about one org's history. Merging them would report
    a run no scan ever observed."""
    scans = [scan("A1", "OrgA", "2026-01-01T00:00:00", [f("R", "A__c")]),
             scan("B1", "OrgB", "2026-02-01T00:00:00", [f("R", "A__c")])]
    lifecycle.annotate_portfolio(scans)
    assert all(s["findings"][0]["survived_scans"] == 1 for s in scans)


# ------------------------------------------------------------ resolution

def test_the_scan_a_finding_disappeared_in_is_stamped_on_its_last_sighting():
    """The scan it was resolved *in* has no row for it, by definition — so the
    stamp has to land on the last record that still reported it."""
    scans = [scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c")]),
             scan("S2", "Org", "2026-02-01T00:00:00", [])]
    stats = lifecycle.annotate(scans)
    assert scans[0]["findings"][0]["resolved_in_scan"] == "S2"
    assert stats["resolved"] == 1


def test_a_finding_still_open_in_the_last_scan_is_not_marked_resolved():
    """Nothing has been observed to clear it. Stamping it would report work as
    done because the history simply stopped."""
    scans = [scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c")])]
    lifecycle.annotate(scans)
    assert "resolved_in_scan" not in scans[0]["findings"][0]


# -------------------------------------------------------------- identity

def test_the_same_rule_on_two_components_is_two_findings():
    scans = [scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c"), f("R", "B__c")]),
             scan("S2", "Org", "2026-02-01T00:00:00", [f("R", "A__c")])]
    lifecycle.annotate(scans)
    assert runs(scans)[("R", "A__c")] == 2
    assert scans[0]["findings"][1]["resolved_in_scan"] == "S2"


def test_a_cluster_rule_keeps_its_members_apart():
    """For the handful of rules where detail says WHICH finding this is rather
    than describing its state, two clusters on one component are two defects."""
    rule = "D1.SEMANTIC_DUPLICATE"
    scans = [scan("S1", "Org", "2026-01-01T00:00:00",
                  [f(rule, "Acct__c", "duplicate cluster — A__c | B__c"),
                   f(rule, "Acct__c", "duplicate cluster — C__c | D__c")]),
             scan("S2", "Org", "2026-02-01T00:00:00",
                  [f(rule, "Acct__c", "duplicate cluster — A__c | B__c")])]
    lifecycle.annotate(scans)
    assert scans[1]["findings"][0]["survived_scans"] == 2
    assert scans[0]["findings"][1]["resolved_in_scan"] == "S2"


# --------------------------------------------------------------- summary

def test_observations_are_counted_apart_from_tickets():
    """An observation the §4.6 gate never ticketed has survived because nobody
    was ever asked to fix it. Averaging it in with the tickets understates how
    stuck the real backlog is."""
    scans = [scan(f"S{i}", "Org", f"2026-0{i}-01T00:00:00",
                  [f("R", "A__c", emits=True), f("R", "B__c", emits=False)])
             for i in (1, 2, 3)]
    lifecycle.annotate(scans)
    summary = lifecycle.survival_summary(scans)
    assert summary["all"]["n"] == 6
    assert summary["ticketed"]["n"] == 3
    assert summary["ticketed"]["stuck"] == 1        # only the run that reached 3


def test_a_single_scan_produces_no_stuck_findings():
    """One scan is not evidence that anything is stuck — it is evidence that
    there is no history yet, and the two must not read alike."""
    scans = [scan("S1", "Org", "2026-01-01T00:00:00", [f("R", "A__c")])]
    lifecycle.annotate(scans)
    assert lifecycle.survival_summary(scans)["ticketed"]["stuck"] == 0
