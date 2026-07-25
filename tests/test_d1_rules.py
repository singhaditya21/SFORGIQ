"""D1 grounding-quality rules.

Several of these are regression tests for false positives the spike actually
shipped and had to fix (recorded in PRD §13) — they are the reason the rules
look the way they do, so they should fail loudly if the logic regresses.
"""

from conftest import field
import orgiq_spike as s


def rule_ids(findings):
    return sorted(f.rule_id for f in findings)


# ---------------------------------------------------------- missing description

def test_missing_description_flags_only_empty():
    fields = [field("Region_Code__c"),
              field("Segment__c", description="Which market segment the account sits in.")]
    out = s.rule_missing_description(fields)
    assert [f.component for f in out] == ["Acct__c.Region_Code__c"]
    assert out[0].confidence == "High"


# --------------------------------------------------------- low-info description

def test_description_that_restates_the_label_is_low_info():
    out = s.rule_low_information_description([field("Segment__c", "Segment", description="Segment")])
    assert rule_ids(out) == ["D1.LOW_INFO_DESCRIPTION"]


def test_description_adding_real_information_is_not_flagged():
    out = s.rule_low_information_description([
        field("Segment__c", "Segment",
              description="Market segment assigned by the pricing team at onboarding.")])
    assert out == []


# ------------------------------------------------------------- cryptic names

def test_vowelless_and_abbreviated_names_are_cryptic():
    out = s.rule_cryptic_api_name([field("Pmt_Mthd__c")])
    assert rule_ids(out) == ["D1.CRYPTIC_API_NAME"]


def test_documented_abbreviation_is_not_cryptic_on_that_ground():
    # An abbreviation only counts against the field when nothing explains it.
    documented = s.rule_cryptic_api_name([
        field("Cust_Tier__c", description="Customer value tier used for support SLAs.")])
    assert all("undocumented abbreviation" not in f.evidence for f in documented)


def test_ordinary_readable_name_is_clean():
    assert s.rule_cryptic_api_name([
        field("Credit_Balance__c", description="Unapplied credit held on the account.")]) == []


# ----------------------------------------------------------- numbered family

def test_numbered_family_groups_members():
    fields = [field("Contact1_Email__c"), field("Contact2_Email__c"), field("Contact3_Email__c")]
    out = s.rule_numbered_family(fields)
    assert rule_ids(out) == ["D1.NUMBERED_FAMILY"]
    assert out[0].confidence == "High"          # 3+ members
    assert "Contact2_Email__c" in out[0].detail


def test_single_numbered_field_is_not_a_family():
    assert s.rule_numbered_family([field("Contact1_Email__c")]) == []


# --------------------------------------------------------- semantic duplicate

def test_abbreviation_and_full_word_are_duplicates():
    out = s.rule_semantic_duplicate([field("Cust_Tier__c"), field("Customer_Tier__c")])
    assert rule_ids(out) == ["D1.SEMANTIC_DUPLICATE"]


def test_type_marker_words_do_not_create_false_duplicates():
    """Regression (PRD §13): stripping words like *date* and *amount* as if they
    were encoding markers made Date_Field__c and Amount_Field__c look identical.
    A count and a sum must never collapse into one finding."""
    out = s.rule_semantic_duplicate([field("Date_Field__c"), field("Amount_Field__c")])
    assert out == []


def test_numbered_family_is_not_reported_as_a_duplicate():
    """Regression (PRD §13): Contact1/Contact2 are a repeating group, handled by
    D1.NUMBERED_FAMILY — the duplicate rule must skip them."""
    fields = [field("Contact1Imported__c"), field("Contact2Imported__c")]
    assert s.rule_semantic_duplicate(fields) == []


def test_entirely_generic_residual_is_not_a_duplicate():
    out = s.rule_semantic_duplicate([field("Record_Value__c"), field("Item_Data__c")])
    assert out == []


# ------------------------------------------------- managed-package fields

def test_no_rule_ticks_a_field_the_org_cannot_change():
    """Found when a calibration worksheet put `nFORCE__LegacyKey__c` in front of
    a practitioner to estimate. Managed-package fields are read-only to the
    subscriber: no description can be added, no name corrected, nothing retired.
    Every finding on one is a ticket nobody can close, and a backlog carrying 86
    of them stops being trusted for the ones that are real."""
    import metadata as md
    managed = field("nFORCE__LegacyKey__c", object_name="Policy__c")
    twin = field("nFORCE__LegacyKey2__c", object_name="Policy__c")
    refs = md.ReportRefs(report_count=3, refs={"Policy__c.Other__c": 2})

    produced = (s.rule_missing_description([managed])
                + s.rule_cryptic_api_name([managed])
                + s.rule_numbered_family([managed, twin])
                + s.rule_semantic_duplicate([managed, twin])
                + s.rule_unreferenced_field([managed], refs)
                + s.rule_low_information_description(
                    [field("nFORCE__Seg__c", "nFORCE Seg", description="nFORCE Seg",
                           object_name="Policy__c")]))
    assert produced == []


def test_an_ordinary_custom_field_is_not_mistaken_for_a_packaged_one():
    """The guard keys on the namespace separator, so it must not swallow a field
    whose own name merely contains an underscore."""
    assert s.is_managed(field("Contact1_Email__c")) is False
    assert s.is_managed(field("Cust_Tier__c")) is False
    assert s.is_managed(field("nFORCE__LegacyKey__c")) is True
    assert s.rule_missing_description([field("Contact1_Email__c")]) != []
