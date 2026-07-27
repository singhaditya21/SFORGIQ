"""Persona capability surfaces and blast radius.

The claim these protect: an agent runs as a persona, so what that persona can
reach is what the agent can reach. Everything here is about not overstating that
surface — and about blast radius meaning "measured", never "assumed".
"""

import metadata as md
import persona


def perm_set(name, perms=(), objs=()):
    return md.PermissionSetMeta(api_name=name, label=name,
                                user_permissions=list(perms),
                                object_perms=[md.ObjectPerm(*o) for o in objs])


def profile(name, perms=(), objs=(), layouts=(), flows=()):
    return md.ProfileMeta(api_name=name, label=name, user_permissions=list(perms),
                          object_perms=[md.ObjectPerm(*o) for o in objs],
                          layout_assignments=tuple(layouts), flow_access=tuple(flows))


# ObjectPerm(object, allow_edit, allow_delete, modify_all, view_all)
EDIT = (True, False, False, False)
DELETE = (True, True, False, False)
READ = (False, False, False, False)


def rules(findings):
    return sorted({f.rule_id for f in findings})


# ------------------------------------------------------------- surfaces

def test_a_persona_with_no_grants_has_no_surface():
    p = persona.build_personas(md.OrgMetadata(permission_sets=[perm_set("Empty")]))[0]
    assert p.objects_editable == () and p.unbounded is False and p.reach == 0


def test_layout_assignment_is_what_makes_a_field_visible():
    """FLS says what a persona MAY read; the layout says what is actually put in
    front of them. Conflating the two overstates the surface."""
    meta = md.OrgMetadata(
        profiles=[profile("Agent", objs=[("Policy__c",) + EDIT], layouts=["Policy__c-Main"])],
        layouts=[md.LayoutMeta(api_name="Policy__c-Main", object_name="Policy__c",
                               fields=("Premium__c", "Status__c"), actions=("Recalc",))])
    p = persona.build_personas(meta)[0]
    assert p.fields_visible == ("Policy__c.Premium__c", "Policy__c.Status__c")
    assert p.actions == ("Recalc",)


def test_approvals_and_validation_rules_attach_to_what_the_persona_can_edit():
    meta = md.OrgMetadata(
        profiles=[profile("Agent", objs=[("Policy__c",) + EDIT])],
        approval_processes=[
            md.ApprovalProcessMeta(api_name="Policy__c.Increase", object_name="Policy__c"),
            md.ApprovalProcessMeta(api_name="Claim__c.Settle", object_name="Claim__c"),
        ],
        validation_rules=[
            md.ValidationRuleMeta(api_name="Policy_Needs_Tier", object_name="Policy__c"),
            md.ValidationRuleMeta(api_name="Claim_Needs_Date", object_name="Claim__c"),
        ])
    p = persona.build_personas(meta)[0]
    assert p.approvals == ("Policy__c.Increase",)      # not the Claim one
    assert p.blocked_by == ("Policy_Needs_Tier",)


def test_an_inactive_approval_is_not_a_process_anyone_takes_part_in():
    meta = md.OrgMetadata(
        profiles=[profile("Agent", objs=[("Policy__c",) + EDIT])],
        approval_processes=[md.ApprovalProcessMeta(
            api_name="Policy__c.Old", object_name="Policy__c", active=False)])
    assert persona.build_personas(meta)[0].approvals == ()


# --------------------------------------------------------------- rules

def test_blanket_permissions_make_a_persona_unbounded():
    meta = md.OrgMetadata(permission_sets=[perm_set("Agent", perms=["ModifyAllData"])])
    out = persona.persona_findings(persona.build_personas(meta))
    assert "D4.PERSONA_UNBOUNDED" in rules(out)
    assert [f.severity for f in out if f.rule_id == "D4.PERSONA_UNBOUNDED"] == ["Critical"]


def test_editing_objects_no_layout_ever_shows_is_access_without_a_process():
    meta = md.OrgMetadata(
        profiles=[profile("Agent", layouts=["Policy__c-Main"], objs=[
            ("Policy__c",) + EDIT, ("Claim__c",) + EDIT,
            ("Broker__c",) + EDIT, ("Coverage__c",) + EDIT])],
        layouts=[md.LayoutMeta(api_name="Policy__c-Main", object_name="Policy__c",
                               fields=("Premium__c",))])
    assert "D4.PERSONA_BEYOND_PROCESS" in rules(persona.persona_findings(
        persona.build_personas(meta)))


def test_a_persona_shown_everything_it_can_edit_is_not_flagged():
    meta = md.OrgMetadata(
        profiles=[profile("Agent", layouts=["Policy__c-Main"], objs=[("Policy__c",) + EDIT])],
        layouts=[md.LayoutMeta(api_name="Policy__c-Main", object_name="Policy__c",
                               fields=("Premium__c",))])
    assert "D4.PERSONA_BEYOND_PROCESS" not in rules(persona.persona_findings(
        persona.build_personas(meta)))


def test_delete_rights_are_reported_unless_blanket_access_already_dwarfs_them():
    """Next to Modify All Data, a delete grant is noise — reporting both buries
    the one that matters."""
    plain = md.OrgMetadata(permission_sets=[perm_set("Ops", objs=[("Policy__c",) + DELETE])])
    assert "D4.PERSONA_CAN_DELETE" in rules(persona.persona_findings(
        persona.build_personas(plain)))

    blanket = md.OrgMetadata(permission_sets=[
        perm_set("Ops", perms=["ModifyAllData"], objs=[("Policy__c",) + DELETE])])
    assert "D4.PERSONA_CAN_DELETE" not in rules(persona.persona_findings(
        persona.build_personas(blanket)))


# -------------------------------------------------------- blast radius

def test_blast_radius_counts_reports_layouts_and_personas():
    meta = md.OrgMetadata(
        report_refs=md.ReportRefs(report_count=4, refs={"Policy__c.Premium__c": 3}),
        profiles=[profile("Agent", layouts=["Policy__c-Main"], objs=[("Policy__c",) + EDIT])],
        layouts=[md.LayoutMeta(api_name="Policy__c-Main", object_name="Policy__c",
                               fields=("Premium__c",))])
    idx = persona.blast_index(meta)
    # 3 reports + 1 layout + 1 persona that can see it
    assert persona.radius_for("Policy__c.Premium__c", idx) == 5


def test_a_component_nothing_depends_on_has_a_radius_of_zero():
    idx = persona.blast_index(md.OrgMetadata())
    assert persona.radius_for("Policy__c.Orphan__c", idx) == 0


def test_a_group_component_has_no_single_radius():
    """"Obj [3 fields]" names a cluster, not a thing. Summing its members would
    read as one component with triple the reach."""
    idx = {"Policy__c.A__c": 9}
    assert persona.radius_for("Policy__c [3 fields]", idx) == 0


def test_no_index_means_not_measured_rather_than_nothing_depends_on_it():
    """scan_result passes blast=None when no index was built. That must stay 0
    and must never be read as evidence the component is unused."""
    import scan_result
    from orgiq_spike import Finding
    f = Finding("D1.MISSING_DESCRIPTION", "D1", "Medium", "High", "Policy__c.A__c", "e", "")
    assert scan_result.finding_rows([f], "SCAN-x")[0]["blast_radius"] == 0


# ------------------------------------------------- the surface as a record
#
# What a reviewer signing off an agent actually reads. Findings say which
# personas are wrong; these rows say what every persona can do, which is the
# half of the question a backlog of problems cannot answer.

from conftest import field                                    # noqa: E402


def surface(p, fields=()):
    return persona.surface_rows([p], "SCAN-x", fields)[0]


def test_the_summary_reads_as_the_sentence_a_reviewer_recognises():
    meta = md.OrgMetadata(
        profiles=[profile("Claims Handler", objs=[("Claim__c",) + EDIT],
                          layouts=["Claim__c-Main"], flows=["Triage"])],
        layouts=[md.LayoutMeta(api_name="Claim__c-Main", object_name="Claim__c",
                               fields=("Reserve__c", "Status__c"))],
        validation_rules=[md.ValidationRuleMeta(api_name="Reserve_Required",
                                                object_name="Claim__c")],
        flows=[md.FlowMeta(api_name="Triage", label="Triage")])
    fields = [field(f"F{i}__c", object_name="Claim__c") for i in range(10)]
    row = surface(persona.build_personas(meta)[0], fields)

    assert "edits Claim__c" in row["summary"]
    assert "sees 2 of 10 fields" in row["summary"]
    assert "starts 1 flow" in row["summary"]
    assert "1 validation rule(s) can block it" in row["summary"]


def test_a_permission_set_has_no_visible_field_count_rather_than_zero():
    """Layouts are assigned by profiles. Reporting a permission set as seeing 0
    fields would read as a finding about the persona when it is a fact about
    where layout assignments live — so the count is absent, and the summary says
    why instead of implying a gap."""
    row = surface(persona.build_personas(
        md.OrgMetadata(permission_sets=[perm_set("Integration",
                                                 objs=[("Policy__c",) + EDIT])]))[0])
    assert row["fields_visible"] is None
    assert "sees 0" not in row["summary"]
    assert "no layouts of its own" in row["summary"]


def test_an_unbounded_persona_is_described_by_that_and_not_by_counts():
    """Counting the objects of a persona that reaches every record of every
    object implies a boundary it does not have."""
    row = surface(persona.build_personas(md.OrgMetadata(
        permission_sets=[perm_set("Admin", perms=["ModifyAllData"],
                                  objs=[("Policy__c",) + EDIT])]))[0])
    assert row["unbounded"] is True
    assert "every record of every object" in row["summary"]
    assert "edits Policy__c" not in row["summary"]


def test_the_visible_share_is_a_fraction_of_what_the_persona_may_read():
    """"Sees 2 fields" is a number with nothing to be a fraction of. The
    denominator is the fields on the objects this persona has access to."""
    meta = md.OrgMetadata(
        profiles=[profile("Agent", objs=[("Policy__c",) + EDIT, ("Claim__c",) + READ],
                          layouts=["Policy__c-Main"])],
        layouts=[md.LayoutMeta(api_name="Policy__c-Main", object_name="Policy__c",
                               fields=("A__c",))])
    fields = ([field("A__c", object_name="Policy__c")]
              + [field(f"C{i}__c", object_name="Claim__c") for i in range(4)])
    row = surface(persona.build_personas(meta)[0], fields)
    assert row["fields_visible"] == 1
    assert row["fields_available"] == 5      # both objects it may read, not just one


def test_surfaces_are_ordered_widest_first():
    """The persona worth reviewing is the one that reaches furthest; alphabetical
    order buries it among the narrow ones."""
    meta = md.OrgMetadata(permission_sets=[
        perm_set("A_Narrow", objs=[("X__c",) + READ]),
        perm_set("Z_Blanket", perms=["ViewAllData"], objs=[("X__c",) + EDIT]),
        perm_set("M_Wide", objs=[(f"O{i}__c",) + EDIT for i in range(5)]),
    ])
    names = [r["name"] for r in persona.surface_rows(
        persona.build_personas(meta), "SCAN-x")]
    assert names == ["Z_Blanket", "M_Wide", "A_Narrow"]


def test_two_personas_in_one_scan_never_share_an_id():
    """The id is scoped to the scan and keyed on kind and name — a collision
    would silently overwrite one surface with the other at load time."""
    meta = md.OrgMetadata(profiles=[profile("Ops")],
                          permission_sets=[perm_set("Ops")])
    ids = {r["external_persona_id"] for r in persona.surface_rows(
        persona.build_personas(meta), "SCAN-x")}
    assert len(ids) == 2
