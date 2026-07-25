"""Report-reference parsing, the unreferenced-field rule, the deterministic
grounding metrics, and where a scan's evidence actually comes from.

These cover the things a reviewer is most likely to poke at: that we do not
claim a field is unused when we simply have no reference data, that editing a
description does not re-mint a backlog ticket, that the token numbers are
produced by real code rather than prose — and that `--mode Org` is a collector
selection rather than a string written onto the scan record.
"""

import json

import density
import metadata as md
import org_mode as om
import orgiq_spike as s
from conftest import field


REPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Billing Summary</name>
    <reportType>Billing_Account__c</reportType>
    <columns><field>Billing_Account__c.MRR__c</field></columns>
    <filters><field>Billing_Account__c.Account_Status__c</field></filters>
    <groupingsDown><field>Billing_Account__c.MRR__c</field></groupingsDown>
</Report>
"""


def write_report(tmp_path, name, xml=REPORT_XML):
    d = tmp_path / "main" / "default" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.report-meta.xml").write_text(xml)


# ------------------------------------------------------------ report parsing

def test_reports_are_parsed_and_counted(tmp_path):
    write_report(tmp_path, "Billing_Summary")
    refs = md.parse_reports(tmp_path)
    assert refs.available is True
    assert refs.report_count == 1
    assert refs.referenced("Billing_Account__c", "MRR__c") >= 1
    assert refs.referenced("Billing_Account__c", "Never_Used__c") == 0


def test_a_field_used_twice_in_one_report_counts_once(tmp_path):
    """MRR__c appears as a column AND a grouping — that is one report using it,
    not two, or 'most referenced field' becomes a formatting artefact."""
    write_report(tmp_path, "Billing_Summary")
    refs = md.parse_reports(tmp_path)
    assert refs.referenced("Billing_Account__c", "MRR__c") == 1


def test_no_reports_means_no_reference_data(tmp_path):
    (tmp_path / "main" / "default").mkdir(parents=True)
    refs = md.parse_reports(tmp_path)
    assert refs.available is False and refs.report_count == 0


def test_malformed_report_is_skipped_not_fatal(tmp_path):
    write_report(tmp_path, "Broken", "<Report><columns><field>Trunc")
    write_report(tmp_path, "Good")
    refs = md.parse_reports(tmp_path)
    assert refs.report_count >= 1        # the good one still parsed


# -------------------------------------------------- D1.UNREFERENCED_FIELD

def _unreferenced(fields, refs):
    return [f for f in s.rule_unreferenced_field(fields, refs)
            if f.rule_id == "D1.UNREFERENCED_FIELD"]


def test_unreferenced_rule_stays_silent_without_report_data():
    """The important safety property: with no reports to check against, the tool
    must NOT declare every field dead. Absence of evidence is not evidence."""
    fields = [field("Never_Used__c"), field("Also_Unused__c")]
    assert _unreferenced(fields, md.ReportRefs()) == []


def test_unreferenced_rule_flags_only_fields_no_report_touches(tmp_path):
    write_report(tmp_path, "Billing_Summary")
    refs = md.parse_reports(tmp_path)
    fields = [field("MRR__c", object_name="Billing_Account__c"),
              field("Never_Used__c", object_name="Billing_Account__c")]
    flagged = [f.component for f in _unreferenced(fields, refs)]
    assert any("Never_Used__c" in c for c in flagged)
    assert not any("MRR__c" in c for c in flagged)


def test_unreferenced_findings_are_not_high_confidence(tmp_path):
    """Source mode cannot see integrations or managed packages, so this rule must
    never claim High confidence."""
    write_report(tmp_path, "Billing_Summary")
    refs = md.parse_reports(tmp_path)
    out = _unreferenced([field("Never_Used__c", object_name="Billing_Account__c")], refs)
    assert out and all(f.confidence != "High" for f in out)



def test_reports_on_unrelated_objects_do_not_condemn_a_whole_object():
    """Regression, found running org mode against a real org: the hub's only
    reports were the samples it shipped with, none of which touch the objects
    being scanned. Report data was globally "available", so every field on every
    scanned object was flagged dead and the tool announced that 100% of the
    schema was removable payload. An object no reporting document mentions is
    unobserved, not unused."""
    refs = _refs({"Unrelated__c.Whatever__c": 3})       # reports exist, elsewhere
    fields = [field("Never_Used__c", object_name="Billing_Account__c"),
              field("Also_Never__c", object_name="Billing_Account__c")]
    assert _unreferenced(fields, refs) == []


def test_an_observed_object_still_yields_its_dead_fields():
    """The other half: once a document does look at the object, silence about a
    particular field is meaningful again."""
    refs = _refs({"Billing_Account__c.MRR__c": 2})
    fields = [field("MRR__c", object_name="Billing_Account__c"),
              field("Never_Used__c", object_name="Billing_Account__c")]
    flagged = [f.component for f in _unreferenced(fields, refs)]
    assert flagged == ["Billing_Account__c.Never_Used__c"]

# ------------------------------------------------------------- density

def test_estimate_tokens_grows_with_text_and_is_zero_for_empty():
    assert density.estimate_tokens("") == 0
    assert density.estimate_tokens("Monthly recurring revenue for the account") > \
        density.estimate_tokens("Revenue")


def test_label_restating_description_has_no_semantic_density():
    restating = [field("Segment__c", "Segment", description="Segment")]
    informative = [field("Segment__c", "Segment",
                         description="Market tier assigned by pricing at onboarding.")]
    assert density.semantic_density(restating) == 0.0
    assert density.semantic_density(informative) > 0.5


def test_density_is_zero_when_nothing_is_described():
    assert density.semantic_density([field("A__c"), field("B__c")]) == 0.0


def test_grounding_payload_projects_a_reduction_for_wasteful_metadata():
    fields = [
        field("Segment__c", "Segment", description="Segment"),          # restating
        field("Cust_Tier__c", "Cust Tier"),
        field("Customer_Tier__c", "Customer Tier",
              description="Customer value tier used for support SLAs."),
    ]
    p = density.grounding_payload(fields)
    assert p["current_tokens"] > 0
    assert p["remediated_tokens"] <= p["current_tokens"]


def test_grounding_payload_handles_no_fields():
    for p in (density.grounding_payload([]),
              density.grounding_payload([], _refs({"Acct__c.Live__c": 2}))):
        assert p["current_tokens"] == 0 and p["remediated_tokens"] == 0
        assert set(p["removable"]) == set(density.REMOVABLE_KEYS)
        assert sum(p["removable"].values()) == 0


# --------------------------------------------- payload: retiring dead fields

def _refs(refs: dict, docs: int = 4) -> md.ReportRefs:
    """A ReportRefs that says `refs` are consumed and everything else is dark."""
    return md.ReportRefs(report_count=docs, refs=dict(refs))


def _payload_fields():
    return [
        field("MRR__c", "MRR",
              description="Monthly recurring revenue booked for the account.",
              object_name="Billing_Account__c"),
        field("Legacy_Split_Code__c", "Legacy Split Code",
              description="Split code carried over from the 2011 billing migration.",
              object_name="Billing_Account__c"),
    ]


def test_retiring_unreferenced_fields_shrinks_the_payload_further(tmp_path):
    """The lever the projection was missing: a field nothing reads leaves the
    corpus whole — api name, label and description — not just its description."""
    write_report(tmp_path, "Billing_Summary")          # references MRR__c only
    refs = md.parse_reports(tmp_path)
    fields = _payload_fields()

    blind = density.grounding_payload(fields)
    seeing = density.grounding_payload(fields, refs)

    assert seeing["current_tokens"] == blind["current_tokens"]   # today is today
    assert seeing["remediated_tokens"] < blind["remediated_tokens"]
    assert seeing["removable"]["unreferenced_fields"] > 0
    # the whole footprint goes, not just the description
    assert seeing["removable"]["unreferenced_fields"] > \
        density.estimate_tokens("Split code carried over from the 2011 billing migration.")


def test_payload_projection_is_unchanged_without_report_data():
    """A source tree with no report metadata must not suddenly look like an org
    where every field is dead — the same safety property the rule itself has."""
    fields = _payload_fields()
    baseline = density.grounding_payload(fields)
    for blind in (density.grounding_payload(fields, None),
                  density.grounding_payload(fields, md.ReportRefs())):
        assert blind == baseline
        assert blind["removable"]["unreferenced_fields"] == 0


def test_a_field_only_code_references_is_not_projected_as_retirable():
    """Apex/Flow usage is the other half of the rule's evidence. If the
    projection ignored it, it would claim a saving the backlog never tickets."""
    fields = _payload_fields()
    refs = _refs({"Billing_Account__c.MRR__c": 2})
    dark = density.grounding_payload(fields, refs)
    lit = density.grounding_payload(fields, refs,
                                    frozenset({"legacy_split_code__c"}))
    assert dark["removable"]["unreferenced_fields"] > 0
    assert lit["removable"]["unreferenced_fields"] == 0
    assert lit["remediated_tokens"] == density.grounding_payload(fields)["remediated_tokens"]


def test_projection_retires_exactly_what_the_rule_flags():
    """Same fields, same evidence, one answer — the projection and the backlog
    cannot disagree about which fields are dead."""
    fields = _payload_fields()
    refs = _refs({"Billing_Account__c.MRR__c": 2})
    flagged = {f.component for f in _unreferenced(fields, refs)}
    assert flagged == {"Billing_Account__c.Legacy_Split_Code__c"}

    kept = density.grounding_payload(fields, refs)["remediated_tokens"]
    assert kept == density.estimate_tokens(
        "MRR__c MRR Monthly recurring revenue booked for the account.")


def test_removable_breakdown_sums_to_the_saving():
    """Every removable token is attributed to exactly one play, so the headline
    number is auditable rather than a black box."""
    fields = [
        # referenced, but its description only restates the label
        field("MRR__c", "MRR", description="MRR", object_name="Billing_Account__c"),
        field("Cust_Tier__c", "Cust Tier", object_name="Billing_Account__c"),
        field("Customer_Tier__c", "Customer Tier",
              description="Customer value tier used for support SLAs.",
              object_name="Billing_Account__c"),
        field("Dead_Weight__c", "Dead Weight",
              description="Left over from a migration nobody documented.",
              object_name="Billing_Account__c"),
    ]
    p = density.grounding_payload(fields, _refs({"Billing_Account__c.MRR__c": 2}))

    assert set(p["removable"]) == set(density.REMOVABLE_KEYS)
    assert sum(p["removable"].values()) == p["current_tokens"] - p["remediated_tokens"]
    # all three levers actually fired, so the sum is not trivially satisfied
    assert all(p["removable"][k] > 0 for k in density.REMOVABLE_KEYS)


def test_a_dead_restating_field_is_not_counted_twice():
    """A field that is both dead and label-restating is removed once. Its
    description tokens are credited to the description play, the rest to
    retirement — the newer lever never re-banks an older play's saving."""
    fields = [field("Ghost_Code__c", "Ghost Code", description="Ghost Code",
                    object_name="Billing_Account__c")]
    p = density.grounding_payload(fields, _refs({"Billing_Account__c.Other__c": 1}))

    assert p["remediated_tokens"] == 0                       # nothing survives
    assert sum(p["removable"].values()) == p["current_tokens"]
    assert p["removable"]["restating_descriptions"] > 0
    assert p["removable"]["duplicate_clusters"] == 0


# ================================================= where the evidence comes from
#
# `--mode Org` was a label: it was written onto the scan record while every byte
# of evidence still came from files on disk. These pin the wiring that replaced
# it — which collector each mode runs, and what happens to the metadata when both
# of them run.

FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>{api}</fullName>
    <label>{label}</label>
    <type>Text</type>
    <description>{description}</description>
</CustomField>
"""

PERMSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Agent Integration</label>
    <userPermissions><enabled>true</enabled><name>ModifyAllData</name></userPermissions>
</PermissionSet>
"""


def write_field(tmp_path, api, obj="Billing_Account__c", description="From the repo."):
    d = tmp_path / "main" / "default" / "objects" / obj / "fields"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{api}.field-meta.xml").write_text(
        FIELD_XML.format(api=api, label=api.replace("__c", "").replace("_", " "),
                         description=description))


def write_permission_set(tmp_path, name="Agent_Integration"):
    d = tmp_path / "main" / "default" / "permissionsets"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.permissionset-meta.xml").write_text(PERMSET_XML)


def fake_collector(meta=None, fields=(), seen=None):
    """Stands in for org_mode.collect. The collectors themselves are exercised
    against a live org; what has to be tested here is that the right one is
    called at all."""
    def collect(target_org, **kwargs):
        if seen is not None:
            seen.append(target_org)
        return om.OrgCollection(org=target_org, org_id="00Dfake", org_name="Fake",
                                metadata=meta if meta is not None else md.OrgMetadata(),
                                fields=list(fields))
    return collect


def org_only_metadata():
    """What only an org can give up: record-level statistics for D2."""
    return md.OrgMetadata(record_stats=[
        md.RecordStats("Billing_Account__c", fill_rate=0.3, stale_ratio=0.7,
                       duplicate_rate=0.2, record_count=1200)])


def test_source_mode_parses_the_directory_and_calls_no_collector(tmp_path):
    write_field(tmp_path, "Repo_Only__c")
    seen = []
    ev = s.gather("Source", path=str(tmp_path),
                  collector=fake_collector(seen=seen))
    assert seen == []                                  # no org was contacted
    assert ev.mode == "Source"
    assert [f.api_name for f in ev.fields] == ["Repo_Only__c"]
    assert ev.collection is None
    # D1's own signal has to be set from the field count, or the registry reports
    # a source-mode scan as having read no schema at all.
    assert md.SIGNAL_FIELD_SCHEMA in ev.meta.present_signals()


def test_org_mode_collects_from_the_org_and_not_from_disk(tmp_path):
    write_field(tmp_path, "Repo_Only__c")
    seen = []
    ev = s.gather("Org", target_org="acme",
                  collector=fake_collector(meta=org_only_metadata(),
                                           fields=[field("Org_Only__c")], seen=seen))
    assert seen == ["acme"]
    assert ev.mode == "Org"
    assert [f.api_name for f in ev.fields] == ["Org_Only__c"]
    assert ev.collection is not None and ev.collection.org_id == "00Dfake"
    # The record data no directory can carry is what makes D2 assessable.
    assert "D2" in ev.assessed_dims


def test_org_and_hybrid_modes_refuse_to_run_without_an_org():
    """A scan that quietly falls back to source data while recording "Org" on the
    record is the defect this replaced. It has to fail instead."""
    for mode in ("Org", "Hybrid"):
        try:
            s.gather(mode, path=".", target_org=None)
        except ValueError as exc:
            assert "target-org" in str(exc)
        else:
            raise AssertionError(mode + " mode ran with no org")


def test_source_and_hybrid_modes_refuse_to_run_without_a_path():
    for mode in ("Source", "Hybrid"):
        try:
            s.gather(mode, path=None, target_org="acme")
        except ValueError as exc:
            assert "path" in str(exc)
        else:
            raise AssertionError(mode + " mode ran with no project path")


def test_hybrid_merges_org_signals_with_source_metadata(tmp_path):
    """Each side contributes what the other cannot: rows come only from the org,
    permission sets only from the repo in this fixture, and both sets of fields
    survive."""
    write_field(tmp_path, "Repo_Only__c")
    write_permission_set(tmp_path)
    seen = []
    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector(meta=org_only_metadata(),
                                           fields=[field("Org_Only__c")], seen=seen))
    assert seen == ["acme"]
    assert ev.mode == "Hybrid"
    assert {f.api_name for f in ev.fields} == {"Repo_Only__c", "Org_Only__c"}
    assert ev.meta.field_count == 2
    present = ev.meta.present_signals()
    assert md.SIGNAL_RECORD_STATS in present           # org's contribution
    assert md.SIGNAL_PERMISSION_SETS in present        # the repo's
    assert {"D2", "D4"} <= ev.assessed_dims


def test_hybrid_prefers_the_org_where_both_sides_describe_one_field(tmp_path):
    """The org is the system of record: a repo can be behind it, ahead of it, or
    describing a different org entirely, and a Hybrid scan is a scan OF the org."""
    write_field(tmp_path, "Shared__c", description="what the repo says")
    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector(
                      fields=[field("Shared__c", description="what the org holds",
                                    object_name="Billing_Account__c")]))
    assert len(ev.fields) == 1
    assert ev.fields[0].description == "what the org holds"


def test_hybrid_fills_an_org_signal_the_repo_can_supply(tmp_path):
    """A collector failure is not the end of the dimension when the source tree
    holds the same metadata — but the record has to say that is what happened."""
    write_permission_set(tmp_path)
    write_field(tmp_path, "Repo_Only__c")
    org_meta = md.OrgMetadata()
    org_meta.record_signal(md.SIGNAL_PERMISSION_SETS, md.UNAVAILABLE,
                           "ObjectPermissions query failed — INSUFFICIENT_ACCESS")

    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector(meta=org_meta))
    assert md.SIGNAL_PERMISSION_SETS in ev.meta.present_signals()
    detail = ev.meta.signal_log[md.SIGNAL_PERMISSION_SETS].detail
    assert "INSUFFICIENT_ACCESS" in detail             # why the org could not
    assert "source tree" in detail                     # and where it came from
    assert ev.coverage["D4"].coverage == 1.0


def test_hybrid_keeps_reference_evidence_from_both_sides(tmp_path):
    """A flow collected from the org shadows the repo's copy of the same flow and
    carries no body with it. If the merge recomputed identifiers from the merged
    component list, the source text would vanish and D1.UNREFERENCED_FIELD would
    call a field dead that a flow we had read plainly uses."""
    write_field(tmp_path, "Repo_Only__c")
    flows = tmp_path / "main" / "default" / "flows"
    flows.mkdir(parents=True, exist_ok=True)
    (flows / "Shared_Flow.flow-meta.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
        "<label>Shared</label><processType>AutoLaunchedFlow</processType>"
        "<description>Touches Repo_Only__c.</description></Flow>")

    # The org reports the same flow, from FlowDefinitionView, with no body.
    org_meta = md.OrgMetadata(flows=[md.FlowMeta(api_name="Shared_Flow",
                                                 label="Shared",
                                                 process_type="AutoLaunchedFlow",
                                                 path="FlowDefinitionView/Shared_Flow")])
    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector(meta=org_meta))
    assert "repo_only__c" in ev.code_tokens


def test_hybrid_keeps_report_references_from_both_sides(tmp_path):
    """A report committed in the repo and a report deployed in the org are both
    evidence that a field is in use. Dropping either side would let
    D1.UNREFERENCED_FIELD retire a field a document we actually read consumes —
    and counting both would double a blast radius the payloads cannot prove."""
    write_report(tmp_path, "Billing_Summary")          # references MRR__c
    org_meta = md.OrgMetadata(report_refs=_refs({"Billing_Account__c.Live__c": 4},
                                                docs=9))
    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector(meta=org_meta))
    refs = ev.meta.report_refs
    assert refs.referenced("Billing_Account__c", "MRR__c") == 1      # the repo's
    assert refs.referenced("Billing_Account__c", "Live__c") == 4     # the org's
    assert refs.report_count == 9                     # a floor, never the sum


def test_a_signal_neither_side_collected_stays_missing(tmp_path):
    """The merge fills gaps from the repo; it does not invent them. Nothing in a
    directory carries record-level data, so D2 stays unassessed."""
    write_field(tmp_path, "Repo_Only__c")
    ev = s.gather("Hybrid", path=str(tmp_path), target_org="acme",
                  collector=fake_collector())
    assert md.SIGNAL_RECORD_STATS not in ev.meta.present_signals()
    assert "D2" not in ev.assessed_dims


# ------------------------------------------------- withholding and ingestion

def test_a_rule_whose_evidence_was_never_collected_reports_nothing():
    """D3.NO_SAFE_ACTIONS asserts that NOTHING in the org is invocable. The rule
    pack cannot tell an empty Apex list from an Apex query that came back
    refused; the signal log can, and the finding is withheld."""
    meta = md.OrgMetadata(permission_sets=[md.PermissionSetMeta("Agent")])
    ev = s.Evidence(mode="Org", fields=[], meta=meta)
    assembled = s.assemble_findings(ev)
    assert "D3.NO_SAFE_ACTIONS" not in {f.rule_id for f in assembled.findings}
    assert "D3.NO_SAFE_ACTIONS" in {f.rule_id for f in assembled.withheld}


def test_a_rule_with_its_evidence_still_reports():
    """The other half — withholding must not swallow findings that were earned.
    Flows and Apex were both collected here and neither exposes an action."""
    meta = md.OrgMetadata(flows=[md.FlowMeta(api_name="Screen", process_type="Flow")],
                          apex=[md.ApexClassMeta("Helper", body="public class Helper {}")])
    assembled = s.assemble_findings(s.Evidence(mode="Org", fields=[], meta=meta))
    assert "D3.NO_SAFE_ACTIONS" in {f.rule_id for f in assembled.findings}
    assert assembled.withheld == []


CODE_ANALYZER_V5 = {
    "violations": [{
        "rule": "AvoidSoqlInLoops", "engine": "pmd", "severity": 2,
        "tags": ["Performance", "Apex"], "primaryLocationIndex": 0,
        "locations": [{"file": "/repo/triggers/AccountTrigger.trigger",
                       "startLine": 12}],
        "message": "Avoid SOQL queries inside loops",
    }],
}


def test_ingested_tool_results_are_logged_as_signals_and_keep_their_source(tmp_path):
    """The wiring the reviewer asked for: a free tool's output reaches the
    findings, is attributable to the tool that raised it, and the tools that did
    NOT run are recorded as unavailable rather than passed over in silence."""
    results = tmp_path / "ca.json"
    results.write_text(json.dumps(CODE_ANALYZER_V5))
    meta = md.OrgMetadata(triggers=[md.ApexTriggerMeta("AccountTrigger",
                                                      object_name="Account",
                                                      body="trigger AccountTrigger on "
                                                           "Account (after insert) {}")])
    ev = s.Evidence(mode="Source", fields=[], meta=meta)

    scan = s.ingest_external(ev, code_analyzer=str(results))
    log = ev.meta.signal_log
    assert log[md.SIGNAL_CODEANALYZER].state == md.COLLECTED
    for absent in (md.SIGNAL_OPTIMIZER, md.SIGNAL_HEALTHCHECK):
        assert log[absent].state == md.UNAVAILABLE
        assert log[absent].detail                      # says why, every time

    findings = s.assemble_findings(ev, scan).findings
    ingested = [f for f in findings if getattr(f, "source", "") == "Code Analyzer"]
    assert [f.rule_id for f in ingested] == ["D5.EXT_BULK_SAFETY"]
    assert "pmd" in ingested[0].tool_rule


def test_an_ingested_finding_merges_with_the_native_rule_that_saw_it_too(tmp_path):
    """One defect, two engines, one record — otherwise ingestion re-creates the
    ticket dump the §4.6 gate exists to prevent."""
    results = tmp_path / "ca.json"
    results.write_text(json.dumps(CODE_ANALYZER_V5))
    body = ("trigger AccountTrigger on Account (after insert) {\n"
            "  for (Account a : Trigger.new) {\n"
            "    List<Contact> c = [SELECT Id FROM Contact WHERE AccountId = :a.Id];\n"
            "  }\n}\n")
    meta = md.OrgMetadata(triggers=[md.ApexTriggerMeta("AccountTrigger",
                                                      object_name="Account", body=body)])
    ev = s.Evidence(mode="Source", fields=[], meta=meta)
    assembled = s.assemble_findings(ev, s.ingest_external(ev, code_analyzer=str(results)))

    soql = [f for f in assembled.findings
            if "soql" in f.rule_id.lower() or f.rule_id == "D5.EXT_BULK_SAFETY"]
    assert len(soql) == 1
    assert getattr(soql[0], "source", "") == "Code Analyzer"      # the parser wins
    assert "corroborated by OrgIQ D5.SOQL_IN_LOOP" in soql[0].evidence
    assert assembled.merges
