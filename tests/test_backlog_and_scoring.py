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
    assert len(rows) == 1
    assert set(backlog.BACKLOG_COLUMNS) == set(rows[0].keys())


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
