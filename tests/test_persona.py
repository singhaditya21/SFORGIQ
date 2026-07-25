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
