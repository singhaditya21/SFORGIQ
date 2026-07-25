"""The signal registry, and the org-mode collector's pure logic.

The collectors themselves are exercised against a live org (see the module
docstring in scanner/org_mode.py); what is unit-testable here is everything
that decides what a scan is *allowed to claim* — coverage arithmetic, the
degradation rules, and the parsing that turns org payloads into the same
structures the SFDX parsers produce.
"""

import itertools

import metadata as md
import org_mode as om


# --------------------------------------------------------- signal registry

def test_every_rule_in_the_registry_names_a_real_signal():
    for rid, rule in md.RULE_SIGNALS.items():
        for sig in set(rule.all_of) | set(rule.any_of):
            assert sig in md.SIGNALS, rid + " requires unknown signal " + sig
        assert rule.dimension in md.DIMENSIONS


def test_assessable_dims_matches_the_old_hardcoded_branches():
    """The registry replaced four `if` statements. Over every combination of
    empty/non-empty inputs those statements could see, it must answer the same."""
    def legacy(m):
        dims = set()
        if m.record_stats:
            dims.add("D2")
        if m.flows or m.apex:
            dims.add("D3")
        if m.permission_sets:
            dims.add("D4")
        if m.triggers or any(f.is_record_triggered for f in m.flows):
            dims.add("D5")
        return dims

    flowsets = [[], [md.FlowMeta(api_name="F")],
                [md.FlowMeta(api_name="F", trigger_object="Account")]]
    statsets = [[], [md.RecordStats("Account")],
                [md.RecordStats("A", fill_rate=0.3, stale_ratio=0.5, duplicate_rate=0.2)]]
    for fl, a, t, p, rs in itertools.product(flowsets, [0, 1], [0, 1], [0, 1], statsets):
        m = md.OrgMetadata(
            flows=fl,
            apex=[md.ApexClassMeta("C")] if a else [],
            triggers=[md.ApexTriggerMeta("T")] if t else [],
            permission_sets=[md.PermissionSetMeta("P")] if p else [],
            record_stats=rs)
        assert m.assessable_dims() == legacy(m)


def test_source_mode_metadata_logs_nothing_and_infers_everything():
    """An OrgMetadata built by the SFDX parsers carries no signal log, so
    presence is inferred from content exactly as it always was."""
    m = md.OrgMetadata(flows=[md.FlowMeta(api_name="F")])
    assert m.signal_log == {}
    assert md.SIGNAL_FLOWS in m.present_signals()
    assert md.SIGNAL_APEX not in m.present_signals()


def test_d1_coverage_drops_when_report_metadata_was_not_read():
    """Five of six D1 rules read field metadata alone; only UNREFERENCED_FIELD
    needs reports. Missing reports must cost exactly that one rule."""
    m = md.OrgMetadata(field_count=40)
    d1 = m.coverage("D1")["D1"]
    assert (d1.rules_runnable, d1.rules_total) == (5, 6)
    assert d1.coverage == 5 / 6
    assert d1.status == md.ASSESSED           # 83% clears the 70% threshold
    assert d1.missing_signals == (md.SIGNAL_REPORT_REFERENCES,)
    assert d1.blocked_rules == ("D1.UNREFERENCED_FIELD",)

    m.report_refs = md.ReportRefs(report_count=3, refs={"Account.Name": 3})
    assert m.coverage("D1")["D1"].coverage == 1.0


def test_a_dimension_with_no_field_metadata_is_not_assessed():
    d1 = md.OrgMetadata().coverage("D1")["D1"]
    assert d1.rules_runnable == 0
    assert d1.status == md.NOT_ASSESSED


def test_unreadable_apex_partially_assesses_d3_rather_than_clearing_it():
    """The org has flows but its Apex could not be read. D3 must not be scored
    as if the Apex had been checked and found clean."""
    m = md.OrgMetadata(flows=[md.FlowMeta(api_name="F", process_type="AutoLaunchedFlow")])
    m.record_signal(md.SIGNAL_FLOWS, md.COLLECTED, "1 flow")
    m.record_signal(md.SIGNAL_APEX, md.UNAVAILABLE, "all bodies returned (hidden)")

    d3 = m.coverage("D3")["D3"]
    assert d3.status == md.PARTIALLY_ASSESSED
    assert d3.coverage == 0.5
    # The rule that would assert "nothing callable exists" is the one blocked.
    assert "D3.NO_SAFE_ACTIONS" in d3.blocked_rules
    assert d3.reasons[md.SIGNAL_APEX] == "all bodies returned (hidden)"


def test_a_collected_but_empty_signal_is_present():
    """"We looked and the org has none" is evidence. "We could not look" is not.
    Both leave the list empty, which is why the log exists."""
    looked = md.OrgMetadata()
    looked.record_signal(md.SIGNAL_APEX, md.COLLECTED, "org has no Apex")
    assert md.SIGNAL_APEX in looked.present_signals()

    refused = md.OrgMetadata()
    refused.record_signal(md.SIGNAL_APEX, md.UNAVAILABLE, "query rejected")
    assert md.SIGNAL_APEX not in refused.present_signals()


def test_d2_sub_signals_come_from_recordstats_provenance():
    """An org whose Name field is an auto-number yields fill and staleness but
    no duplicate key. D2 must report two of three, not three of three."""
    m = md.OrgMetadata(record_stats=[
        md.RecordStats("Acct__c", fill_rate=0.5, record_count=100,
                       unavailable=("duplicate_rate",))])
    d2 = m.coverage("D2")["D2"]
    assert d2.coverage == 2 / 3
    assert d2.status == md.PARTIALLY_ASSESSED       # below the 70% threshold
    assert d2.blocked_rules == ("D2.DUPLICATE_RECORDS",)
    assert md.SIGNAL_DUPLICATES in d2.missing_signals


def test_fully_measured_record_stats_give_d2_full_coverage():
    m = md.OrgMetadata(record_stats=[md.RecordStats("Acct__c", fill_rate=0.5)])
    assert m.coverage("D2")["D2"].coverage == 1.0


def test_blocked_rules_are_dropped_from_findings():
    class F:
        def __init__(self, rule_id):
            self.rule_id = rule_id

    m = md.OrgMetadata(flows=[md.FlowMeta(api_name="F")])
    m.record_signal(md.SIGNAL_APEX, md.UNAVAILABLE, "hidden")
    kept, dropped = m.drop_blocked([F("D3.INACTIVE_ACTION"), F("D3.NO_SAFE_ACTIONS"),
                                    F("D9.NOT_IN_REGISTRY")])
    assert [f.rule_id for f in kept] == ["D3.INACTIVE_ACTION", "D9.NOT_IN_REGISTRY"]
    assert [f.rule_id for f in dropped] == ["D3.NO_SAFE_ACTIONS"]


def test_external_signals_are_reserved_and_absent():
    m = md.OrgMetadata()
    for sig in (md.SIGNAL_OPTIMIZER, md.SIGNAL_HEALTHCHECK, md.SIGNAL_CODEANALYZER):
        assert sig in md.SIGNALS
        assert sig not in m.present_signals()


def test_explain_names_the_missing_signal_and_why():
    m = md.OrgMetadata(field_count=10)
    m.record_signal(md.SIGNAL_REPORT_REFERENCES, md.UNAVAILABLE, "describe returned FORBIDDEN")
    text = m.coverage("D1")["D1"].explain()
    assert "83.3%" in text and "5/6" in text
    assert md.SIGNAL_REPORT_REFERENCES in text and "FORBIDDEN" in text


# ------------------------------------------------------------- org mode

def test_secrets_never_reach_a_note():
    dirty = ("INVALID_SESSION_ID: session 00Dfj00000XMBg9!AQEAQMxyz.abc-123_DEF456ghi "
             "with Bearer 00Dxx0000001gPzEAI9aBcDeFgHiJkLmNoP expired")
    clean = om._redact(dirty)
    assert "00Dfj00000XMBg9!" not in clean
    assert "[redacted]" in clean
    assert "INVALID_SESSION_ID" in clean       # the useful part survives


def test_managed_components_keep_their_namespace_in_the_api_name():
    assert om._api_name({"NamespacePrefix": "SvcCopilotTmpl", "ApiName": "CancelOrder"}) \
        == "SvcCopilotTmpl__CancelOrder"
    assert om._api_name({"NamespacePrefix": None, "ApiName": "My_Flow"}) == "My_Flow"


def test_report_reference_walker_finds_columns_and_ignores_titles():
    """The Analytics describe payload is JSON where source mode reads XML, but
    the tokens land in the same key space."""
    payload = {
        "reportMetadata": {
            "name": "Pipeline by Rep",                 # the report's title, not a field
            "reportType": {"type": "OpportunityList"},
            "detailColumns": ["OPPORTUNITY.NAME", "Opportunity.Amount"],
            "aggregates": ["s!Opportunity.Amount"],
            "groupingsDown": [{"name": "Opportunity.StageName", "sortOrder": "Asc"}],
            "reportFilters": [{"column": "Opportunity.CloseDate", "operator": "greaterThan"}],
            "buckets": [{"sourceColumnName": "Account.Industry"}],
        }
    }
    tokens = set()
    om._walk_report_refs(payload["reportMetadata"], tokens)
    assert "Opportunity.Amount" in tokens
    assert "Opportunity.StageName" in tokens
    assert "Opportunity.CloseDate" in tokens
    assert "Account.Industry" in tokens
    assert "Pipeline by Rep" not in tokens

    keys = om._canonical_keys(tokens)
    assert "Opportunity.Amount" in keys
    assert "Amount" in keys                    # bare fallback, as parse_reports stores
    assert "Industry" in keys


def test_org_collected_refs_resolve_through_the_same_lookup_as_source_mode():
    refs = md.ReportRefs()
    md._absorb(refs, om._canonical_keys({"OPPORTUNITY.NAME", "Opportunity.Amount"}))
    refs.report_count = 1
    assert refs.available
    # ReportRefs.referenced is case-insensitive; org and source tokens agree.
    assert refs.referenced("Opportunity", "Amount") == 1
    assert refs.referenced("Opportunity", "Name") == 1


def test_fill_candidates_are_bounded_deterministic_and_custom_first():
    desc = {"fields": [
        {"name": "Id", "filterable": True, "nillable": False, "custom": False},
        {"name": "Zeta__c", "filterable": True, "nillable": True, "custom": True},
        {"name": "Alpha__c", "filterable": True, "nillable": True, "custom": True},
        {"name": "Formula__c", "filterable": True, "nillable": True, "custom": True,
         "calculated": True},
        {"name": "Notes__c", "filterable": False, "nillable": True, "custom": True},
        {"name": "AccountId", "filterable": True, "nillable": True, "custom": False,
         "type": "reference"},
        {"name": "Industry", "filterable": True, "nillable": True, "custom": False},
    ]}
    picked = om._fill_candidates(desc, 10)
    assert picked == ["Alpha__c", "Zeta__c", "Industry"]     # custom first, sorted
    assert om._fill_candidates(desc, 2) == ["Alpha__c", "Zeta__c"]
    assert om._fill_candidates(desc, 10) == picked           # deterministic


def test_duplicate_probe_refuses_an_ungroupable_name_field():
    """An auto-number Name is not a duplicate key. The honest answer is that
    this org offers no duplicate signal for the object, not that some other
    column will stand in."""
    autonumber = {"fields": [{"name": "Name", "nameField": True, "groupable": False,
                              "type": "string"},
                             {"name": "Rule_Id__c", "groupable": True, "type": "string"}]}
    assert om._dup_key(autonumber) == ""

    named = {"fields": [{"name": "Name", "nameField": True, "groupable": True,
                         "type": "string"}]}
    assert om._dup_key(named) == "Name"


def test_soql_literals_are_escaped():
    assert om._q("O'Brien__c") == "O\\'Brien__c"
