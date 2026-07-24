"""Backlog gating / idempotency (PRD §4.6) and the scan-result scoring model."""

import csv

import backlog
import scan_result
from conftest import field
from orgiq_spike import Finding


def finding(rule="D1.MISSING_DESCRIPTION", dim="D1", sev="Medium", conf="Medium",
            component="Acct__c.A__c", evidence="e", detail=""):
    return Finding(rule, dim, sev, conf, component, evidence, detail)


# ------------------------------------------------------- §4.6 emission gate

def test_gate_requires_medium_severity_and_medium_confidence():
    assert backlog.emits_to_backlog(finding(sev="High", conf="High")) is True
    assert backlog.emits_to_backlog(finding(sev="Medium", conf="Medium")) is True
    assert backlog.emits_to_backlog(finding(sev="Low", conf="High")) is False
    assert backlog.emits_to_backlog(finding(sev="High", conf="Low")) is False


def test_held_back_findings_stay_out_of_the_csv(tmp_path):
    findings = [finding(sev="High", conf="High"), finding(sev="Low", conf="High",
                                                          component="Acct__c.B__c")]
    out = tmp_path / "backlog.csv"
    written, observations = backlog.write_csv(findings, "SrcOrg", str(out))
    assert (written, observations) == (1, 1)
    rows = list(csv.DictReader(out.open()))
    assert set(backlog.BACKLOG_COLUMNS) == set(rows[0].keys())
    # One epic's worth of scaffolding around exactly one ticketed finding.
    assert [r["Issue Type"] for r in rows] == ["Epic", "Task"]
    assert [r["Salesforce Component"] for r in rows if r["Issue Type"] == "Task"] \
        == ["Acct__c.A__c"]
    # Both findings share an epic, so the held-back one could leak into the
    # parent's rollup as easily as into a row of its own. Neither is allowed.
    assert "Acct__c.B__c" not in out.read_text()


# --------------------------------------------------------- idempotent ids

def test_external_id_is_stable_for_the_same_finding_and_source():
    a = backlog._external_id(finding(), "OrgA")
    b = backlog._external_id(finding(), "OrgA")
    assert a == b and a.startswith("OIQ-")


def test_external_id_varies_by_source_and_by_detail():
    base = finding()
    assert backlog._external_id(base, "OrgA") != backlog._external_id(base, "OrgB")
    # Two duplicate clusters on one object render the same component; `detail`
    # is what keeps their ids distinct (regression — it caused upsert collisions).
    g1 = finding(rule="D1.SEMANTIC_DUPLICATE", component="Acct__c [2 fields]", detail="A__c | B__c")
    g2 = finding(rule="D1.SEMANTIC_DUPLICATE", component="Acct__c [2 fields]", detail="C__c | D__c")
    assert backlog._external_id(g1, "OrgA") != backlog._external_id(g2, "OrgA")


def test_editing_descriptive_state_does_not_re_mint_the_ticket():
    """Regression: the id used to hash `detail`, which carries mutable state — so
    rewording a description or a label orphaned the tracked ticket and created a
    new one. That silently destroyed burn-down across re-scans, which is the
    tool's core claim."""
    a = finding(rule="D1.LOW_INFO_DESCRIPTION", component="Acct__c.Seg__c",
                detail="label='Seg' desc='Seg'")
    b = finding(rule="D1.LOW_INFO_DESCRIPTION", component="Acct__c.Seg__c",
                detail="label='Seg' desc='Segment value'")
    assert backlog._external_id(a, "Org") == backlog._external_id(b, "Org")

    c = finding(component="Acct__c.X__c", detail="label='Old Label'")
    d = finding(component="Acct__c.X__c", detail="label='New Label'")
    assert backlog._external_id(c, "Org") == backlog._external_id(d, "Org")


def test_identity_bearing_detail_still_separates_distinct_findings():
    """The other half: for group rules the detail IS the identity, so two distinct
    clusters on one object must keep distinct ids (the collision that broke bulk
    upsert)."""
    for rule in sorted(backlog._IDENTITY_DETAIL_RULES):
        one = finding(rule=rule, component="Acct__c [2 fields]", detail="A__c | B__c")
        two = finding(rule=rule, component="Acct__c [2 fields]", detail="C__c | D__c")
        assert backlog._external_id(one, "Org") != backlog._external_id(two, "Org"), rule


def test_backlog_rows_carry_provenance():
    """Without a source column an ingested Optimizer finding would be
    indistinguishable from one of our own rules."""
    assert 'Source' in backlog.BACKLOG_COLUMNS
    rows, _ = backlog.to_rows([finding(sev="High", conf="High")], "Org")
    assert rows[0]['Source'] == 'OrgIQ'


# -------------------------------------------------------- epic clustering
#
# Three playbook epics, deliberately interleaved on input and with the two
# members of one epic separated by severity, so a passing grouping assertion
# cannot be an accident of the severity sort.

def mixed_findings():
    return [
        finding(component="Acct__c.B__c"),                                  # epic 1, Medium
        finding(rule="D1.CRYPTIC_API_NAME", sev="High", conf="Medium",
                component="Acct__c.X1__c"),                                 # epic 2
        finding(rule="D1.UNREFERENCED_FIELD", component="Acct__c.Z__c"),    # epic 3
        finding(sev="High", conf="High", component="Acct__c.A__c"),         # epic 1, High
    ]


def epics_and_tasks(rows):
    return ([r for r in rows if r["Issue Type"] == "Epic"],
            [r for r in rows if r["Issue Type"] == "Task"])


def test_a_gated_finding_emits_an_epic_and_a_child_linked_to_it():
    """Epic Link on the child is the only thing that makes Jira's importer parent
    it. Lose it and a portfolio import lands as a heap of loose tickets — the
    "four-thousand-ticket dump nobody imports" the §4.6 gate exists to prevent."""
    rows, _ = backlog.to_rows([finding(sev="High", conf="High")], "Org")
    epic, task = rows
    assert (epic["Issue Type"], task["Issue Type"]) == ("Epic", "Task")
    assert epic["Epic Name"], "an epic that does not name itself cannot be linked to"
    assert task["Epic Link"] == epic["Epic Name"]
    assert epic["Epic Link"] == ""            # nothing parents an epic


def test_children_carry_no_epic_name_of_their_own():
    """Jira reads *any* row with an Epic Name as an epic. A named child imports as
    a second, childless epic and silently detaches the work from its parent."""
    epics, tasks = epics_and_tasks(backlog.to_rows(mixed_findings(), "Org")[0])
    assert all(t["Epic Name"] == "" for t in tasks)
    assert all(e["Epic Name"] for e in epics)


def test_epic_story_points_are_the_sum_of_their_children():
    """The epic row is what someone sizes a sprint off. If it does not add up to
    the work hanging under it, the estimate is worse than no estimate."""
    rows, _ = backlog.to_rows(mixed_findings(), "Org")
    epics, tasks = epics_and_tasks(rows)
    for e in epics:
        children = [t for t in tasks if t["Epic Link"] == e["Epic Name"]]
        assert children, f"epic {e['Epic Name']} has no children"
        assert e["Story Points (provisional)"] == \
            sum(t["Story Points (provisional)"] for t in children)


def test_epic_external_id_is_stable_across_runs_and_distinct_per_org():
    """Re-import is an upsert. An epic id that drifts between scans orphans the
    parent the burn-down is tracked on; an id (or name) shared across orgs
    collapses 24 orgs' "Retire unreferenced fields" into one epic in a merged
    portfolio file."""
    def epic_row(findings, source):
        return backlog.to_rows(findings, source)[0][0]

    a = epic_row([finding(sev="High", conf="High")], "OrgA")
    assert a["External ID"].startswith("OIQ-EPIC-")
    assert epic_row([finding(sev="High", conf="High")], "OrgA")["External ID"] \
        == a["External ID"]

    # The epic must outlive its membership: children come and go between scans.
    grown = epic_row([finding(sev="High", conf="High"),
                      finding(component="Acct__c.C__c")], "OrgA")
    assert grown["External ID"] == a["External ID"]

    b = epic_row([finding(sev="High", conf="High")], "OrgB")
    assert b["External ID"] != a["External ID"]
    assert b["Epic Name"] != a["Epic Name"]


def test_an_epic_row_appears_immediately_before_its_own_children():
    """The CSV is read by people before it is read by Jira. Interleaved rows still
    import, but nobody can review a plan out of them — and an epic emitted in two
    separate blocks reads as two different pieces of work."""
    rows, _ = backlog.to_rows(mixed_findings(), "Org")
    current, seen = None, []
    for row in rows:
        if row["Issue Type"] == "Epic":
            current = row["Epic Name"]
            assert current not in seen, f"{current} emitted in two separate blocks"
            seen.append(current)
        else:
            assert current is not None, "a task was emitted before any epic row"
            assert row["Epic Link"] == current, "a task sits under the wrong epic"
    assert len(seen) == 3


def test_include_epics_false_still_produces_the_flat_shape():
    """Callers that only want the findings (the portfolio merge, ad-hoc exports)
    must be able to opt out without inheriting rows that are not findings."""
    findings = mixed_findings()
    rows, _ = backlog.to_rows(findings, "Org", include_epics=False)
    assert len(rows) == len(findings)
    assert all(r["Issue Type"] == "Task" for r in rows)
    assert all(r["Epic Link"] == "" for r in rows)
    assert all(r["Epic Name"] for r in rows)      # flat rows keep the epic as a label


def test_write_csv_ticket_count_counts_children_not_epic_rows(tmp_path):
    """The CLI prints this number as "findings that became tickets". Counting the
    epic scaffolding into it inflates every report the tool produces."""
    out = tmp_path / "backlog.csv"
    written, observations = backlog.write_csv(mixed_findings(), "Org", str(out))
    rows = list(csv.DictReader(out.open()))
    epics, tasks = epics_and_tasks(rows)
    assert (len(epics), len(tasks)) == (3, 4)     # the epics are really in the file
    assert (written, observations) == (4, 0)
    assert written != len(rows)


def test_findings_held_back_by_the_gate_create_neither_an_epic_nor_a_task():
    """An epic is only justified by children that cleared §4.6. One raised for
    held-back findings is a ticket for work the tool deliberately declined to
    raise — the gate leaking back in through the parent row."""
    below_gate = [finding(sev="Low", conf="High", component="Acct__c.Q__c"),
                  finding(rule="D1.UNREFERENCED_FIELD", sev="High", conf="Low",
                          component="Acct__c.R__c")]
    rows, observations = backlog.to_rows(below_gate, "Org")
    assert rows == []
    assert observations == 2

    # ...and one gated finding does not drag a neighbouring epic in with it.
    rows, observations = backlog.to_rows(
        below_gate + [finding(sev="High", conf="High")], "Org")
    epics, tasks = epics_and_tasks(rows)
    assert len(epics) == 1 and len(tasks) == 1
    assert observations == 2
    assert "Retire unreferenced fields" not in epics[0]["Epic Name"]


def test_epic_link_column_sits_next_to_epic_name():
    """Jira's importer maps by column, and dashboard/src/lib/data.js hand-writes
    the same 17 columns. A drift here is invisible until an import mis-maps."""
    cols = backlog.BACKLOG_COLUMNS
    assert len(cols) == 17
    assert cols[cols.index("Epic Name") + 1] == "Epic Link"


def test_every_rule_has_a_remediation_playbook_entry():
    """A rule with no playbook silently falls back to generic text in the
    backlog — catch that at build time instead."""
    import rules_ext, orgiq_spike
    known = set(backlog._PLAYBOOK)
    d1 = {rid for rid, _ in orgiq_spike.RULES}
    assert d1 <= known, f"D1 rules missing from playbook: {d1 - known}"
    for rid in ["D2.LOW_FILL_RATE", "D3.NO_SAFE_ACTIONS", "D3.INACTIVE_ACTION",
                "D4.MODIFY_ALL_DATA", "D4.DELETE_GRANTED", "D5.SOQL_IN_LOOP",
                "D5.TRIGGER_AND_FLOW"]:
        assert rid in known, f"{rid} missing from playbook"


# ------------------------------------------------------------- bands

def test_readiness_bands_match_the_rubric():
    assert scan_result.band_for(0) == "Not Ready"
    assert scan_result.band_for(40) == "Not Ready"
    assert scan_result.band_for(41) == "Foundational Work Required"
    assert scan_result.band_for(60) == "Foundational Work Required"
    assert scan_result.band_for(61) == "Conditionally Ready"
    assert scan_result.band_for(80) == "Conditionally Ready"
    assert scan_result.band_for(81) == "Ready"
    assert scan_result.band_for(100) == "Ready"


# --------------------------------------------------- assessed vs unassessed

def test_unassessed_dimensions_are_excluded_from_the_composite():
    fields = [field("A__c", description="Documented well enough to ground on.")]
    res = scan_result.build(fields, [], "Src", assessed_dims=frozenset({"D1"}))
    rows = {d["dimension"][:2]: d for d in res["dimensions"]}
    assert rows["D1"]["in_composite"] is True
    for code in ("D2", "D3", "D4", "D5"):
        assert rows[code]["in_composite"] is False
        assert rows[code]["score"] is None
        assert rows[code]["assessment_status"] == "Not Assessed"
        assert rows[code]["missing_signals"]          # says *why*


def test_composite_averages_only_assessed_dimensions():
    fields = [field("A__c", description="Documented well enough to ground on.")]
    res = scan_result.build(fields, [], "Src",
                            assessed_dims=frozenset({"D1", "D2", "D3", "D4", "D5"}))
    scores = [d["score"] for d in res["dimensions"]]
    assert all(s is not None for s in scores)
    assert res["scan"]["composite_score"] == round(sum(scores) / len(scores))


# -------------------------------------------------------------- gate caps

def test_critical_d4_finding_caps_the_composite_at_60():
    fields = [field("A__c", description="Documented well enough to ground on.")]
    critical = finding(rule="D4.MODIFY_ALL_DATA", dim="D4", sev="Critical", conf="High",
                       component="Agent")
    res = scan_result.build(fields, [critical], "Src",
                            assessed_dims=frozenset({"D1", "D4"}))
    assert res["scan"]["composite_score"] <= 60
    assert res["scan"]["gate_applied"] is True
    assert "Critical D4" in res["scan"]["gate_reason"]


def test_no_gate_reason_when_no_cap_applies():
    fields = [field("A__c", description="Documented well enough to ground on.")]
    res = scan_result.build(fields, [], "Src", assessed_dims=frozenset({"D1"}))
    assert res["scan"]["gate_applied"] is False
    assert res["scan"]["gate_reason"] == ""


# --------------------------------------------------- finding record shape

def test_findings_carry_everything_the_salesforce_schema_needs():
    fields = [field("A__c")]
    res = scan_result.build(fields, [finding()], "Src")
    row = res["findings"][0]
    for key in ("external_finding_id", "rule_id", "dimension", "severity", "confidence",
                "component_type", "component_api_name", "evidence", "remediation",
                "effort_points", "blast_radius", "emits_to_backlog", "rule_maturity", "status"):
        assert key in row, f"missing {key}"
    assert row["status"] == "Open"
    assert row["rule_maturity"] == "experimental"
