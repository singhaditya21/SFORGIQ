"""Report-reference parsing, the unreferenced-field rule, and the deterministic
grounding metrics.

These cover the three things a reviewer is most likely to poke at: that we do not
claim a field is unused when we simply have no reference data, that editing a
description does not re-mint a backlog ticket, and that the token numbers are
produced by real code rather than prose.
"""

import density
import metadata as md
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
