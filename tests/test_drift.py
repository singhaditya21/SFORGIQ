"""Cross-org drift.

The rule this file exists to protect: a difference is only worth reporting when
someone was relying on the two orgs matching. Everything else here follows from
that — which org is the reference, which direction the gap runs, and how loudly
to say so.
"""

import drift


def snap(name, org_type, fields=(), triggers=(), flows=(), perms=()):
    return drift.OrgSnapshot(name=name, org_type=org_type, fields=tuple(fields),
                             triggers=tuple(triggers), flows=tuple(flows),
                             perm_sets=tuple(perms))


BASE = tuple(f"Policy__c.F{i}__c" for i in range(30))


def rules(findings):
    return sorted({f.rule_id for f in findings})


# ------------------------------------------------------------- reference

def test_production_is_the_reference():
    """The agent runs in production, so production is what everything else is
    measured against — not the biggest org, not the first one."""
    prod = snap("prod", "Production", BASE[:10])
    uat = snap("uat", "UAT", BASE)                 # larger, but not the reference
    ref, caveat = drift.pick_reference([uat, prod])
    assert ref.name == "prod" and caveat == ""


def test_without_production_the_largest_org_stands_in_and_says_so():
    uat = snap("uat", "UAT", BASE)
    qa = snap("qa", "QA", BASE[:5])
    ref, caveat = drift.pick_reference([qa, uat])
    assert ref.name == "uat"
    assert "no production org" in caveat


def test_the_reference_is_not_reported_against_itself():
    prod = snap("prod", "Production", BASE)
    out = drift.compare_estate([prod, snap("uat", "UAT", BASE[:10])])
    assert "prod" not in out


def test_a_single_org_estate_has_nothing_to_compare():
    assert drift.compare_estate([snap("prod", "Production", BASE)]) == {}


# ------------------------------------------------------------- direction

def test_an_org_missing_production_fields_is_behind():
    out = drift.compare_estate([snap("prod", "Production", BASE),
                                snap("uat", "UAT", BASE[:20])])
    assert "DRIFT.BEHIND_REFERENCE" in rules(out["uat"])


def test_an_org_with_extra_fields_is_ahead():
    out = drift.compare_estate([snap("prod", "Production", BASE[:20]),
                                snap("dev", "Developer", BASE)])
    assert "DRIFT.AHEAD_OF_REFERENCE" in rules(out["dev"])


def test_identical_orgs_produce_nothing():
    out = drift.compare_estate([snap("prod", "Production", BASE),
                                snap("uat", "UAT", BASE)])
    assert out == {}


def test_a_couple_of_fields_out_of_step_is_not_drift():
    """Every org is a field or two adrift. Reporting that trains people to
    ignore the ones that matter."""
    out = drift.compare_estate([snap("prod", "Production", BASE),
                                snap("uat", "UAT", BASE[:-2])])
    assert out == {}


# -------------------------------------------------------------- severity

def test_a_uat_org_behind_production_outranks_a_dev_org_ahead_of_it():
    """UAT is where sign-off happens, so a gap there invalidates the test that
    was signed off. A developer sandbox running ahead is that sandbox working."""
    out = drift.compare_estate([
        snap("prod", "Production", BASE),
        snap("uat", "UAT", BASE[:8]),        # behind by 22
        snap("dev", "Developer", BASE + tuple(f"New{i}__c" for i in range(22))),
    ])
    uat = next(f for f in out["uat"] if f.rule_id == "DRIFT.BEHIND_REFERENCE")
    dev = next(f for f in out["dev"] if f.rule_id == "DRIFT.AHEAD_OF_REFERENCE")
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    assert rank[uat.severity] < rank[dev.severity]


def test_an_org_off_the_release_path_is_not_rated_as_a_broken_control():
    """An acquisition is not pretending to match production. Rating it like a
    stale UAT buries the orgs that genuinely break a sign-off."""
    out = drift.compare_estate([snap("prod", "Production", BASE),
                                snap("acquired", "Other", BASE[:4])])
    behind = next(f for f in out["acquired"] if f.rule_id == "DRIFT.BEHIND_REFERENCE")
    assert behind.severity in ("Low", "Medium")


# ---------------------------------------------------- automation & perms

def test_diverged_automation_and_permissions_are_reported():
    out = drift.compare_estate([
        snap("prod", "Production", BASE, triggers=("A",), perms=("Agent",)),
        snap("uat", "UAT", BASE, triggers=("A", "B"), perms=("Agent", "Extra")),
    ])
    assert "DRIFT.AUTOMATION_DIVERGED" in rules(out["uat"])
    assert "DRIFT.PERMISSION_DIVERGED" in rules(out["uat"])


# -------------------------------------------------------------- scoring

def test_drift_findings_sit_outside_the_five_dimensions():
    """Drift describes a PAIR of orgs. Letting it into D1-D5 would score this
    org for the state of another one."""
    out = drift.compare_estate([snap("prod", "Production", BASE),
                                snap("uat", "UAT", BASE[:10])])
    assert all(f.dimension == "Drift" for fs in out.values() for f in fs)
