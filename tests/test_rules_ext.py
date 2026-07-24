"""D2–D5 rule packs, run over parsed metadata structures."""

import metadata as md
import rules_ext as rx


def ids(findings):
    return sorted({f.rule_id for f in findings})


# --------------------------------------------------------------- D2

def test_d2_flags_poor_data_and_leaves_good_data_alone():
    bad = rx.d2_data_foundation([md.RecordStats("Account", fill_rate=0.30,
                                                stale_ratio=0.70, duplicate_rate=0.20)])
    assert ids(bad) == ["D2.DUPLICATE_RECORDS", "D2.LOW_FILL_RATE", "D2.STALE_DATA"]
    assert [f.severity for f in bad if f.rule_id == "D2.LOW_FILL_RATE"] == ["High"]

    good = rx.d2_data_foundation([md.RecordStats("Account", fill_rate=0.95,
                                                 stale_ratio=0.05, duplicate_rate=0.01)])
    assert good == []


# --------------------------------------------------------------- D3

def test_d3_reports_when_nothing_is_callable():
    out = rx.d3_action_surface(flows=[], apex=[])
    assert ids(out) == ["D3.NO_SAFE_ACTIONS"]


def test_d3_flags_undocumented_and_inactive_actions():
    flows = [md.FlowMeta(api_name="F1", process_type="AutoLaunchedFlow", status="Active"),
             md.FlowMeta(api_name="F2", process_type="AutoLaunchedFlow", status="Draft",
                         description="Documented.")]
    out = rx.d3_action_surface(flows, apex=[])
    assert "D3.UNDOCUMENTED_ACTION" in ids(out)      # F1 has no description
    assert "D3.INACTIVE_ACTION" in ids(out)          # F2 is Draft
    assert "D3.NO_SAFE_ACTIONS" not in ids(out)      # something is callable


def test_d3_flags_invocable_apex_without_a_test():
    svc = md.ApexClassMeta(api_name="Svc", body="@InvocableMethod(label='Go') void go(){}")
    assert "D3.APEX_NO_TESTS" in ids(rx.d3_action_surface([], [svc]))

    test = md.ApexClassMeta(api_name="SvcTest", body="@isTest class SvcTest { Svc.go(); }")
    assert "D3.APEX_NO_TESTS" not in ids(rx.d3_action_surface([], [svc, test]))


# --------------------------------------------------------------- D4

def test_d4_modify_all_data_is_critical():
    ps = md.PermissionSetMeta(api_name="Agent", user_permissions=["ModifyAllData"])
    out = rx.d4_blast_radius([ps])
    assert out[0].rule_id == "D4.MODIFY_ALL_DATA"
    assert out[0].severity == "Critical"


def test_d4_object_level_breadth():
    ps = md.PermissionSetMeta(api_name="Agent", object_perms=[
        md.ObjectPerm("Account", allow_edit=True, modify_all=True),
        md.ObjectPerm("Contact", allow_edit=True, allow_delete=True),
        md.ObjectPerm("Case", allow_edit=True),          # ordinary — not flagged
    ])
    got = ids(rx.d4_blast_radius([ps]))
    assert got == ["D4.DELETE_GRANTED", "D4.WIDE_OBJECT_ACCESS"]


def test_d4_clean_permission_set_produces_nothing():
    ps = md.PermissionSetMeta(api_name="Agent", user_permissions=[],
                              object_perms=[md.ObjectPerm("Account", allow_edit=True)])
    assert rx.d4_blast_radius([ps]) == []


# --------------------------------------------------------------- D5

DIRTY = ("trigger T on Account (after insert) { for (Account a : Trigger.new) { "
         "List<Contact> c = [SELECT Id FROM Contact]; insert new Contact(); } }")
CLEAN = "trigger T on Account (after insert) { if (H.hasRun) return; H.handle(Trigger.new); }"


def test_d5_flags_unbulkified_unguarded_trigger():
    t = md.ApexTriggerMeta(api_name="T", object_name="Account", body=DIRTY)
    got = ids(rx.d5_automation_collision([t], flows=[]))
    assert got == ["D5.DML_IN_LOOP", "D5.NO_RECURSION_GUARD", "D5.SOQL_IN_LOOP"]


def test_d5_clean_trigger_is_quiet():
    t = md.ApexTriggerMeta(api_name="T", object_name="Account", body=CLEAN)
    assert rx.d5_automation_collision([t], flows=[]) == []


def test_d5_detects_multiple_triggers_on_one_object():
    ts = [md.ApexTriggerMeta(api_name="A", object_name="Account", body=CLEAN),
          md.ApexTriggerMeta(api_name="B", object_name="Account", body=CLEAN)]
    assert "D5.MULTIPLE_TRIGGERS" in ids(rx.d5_automation_collision(ts, flows=[]))


def test_d5_detects_trigger_and_record_flow_on_same_object():
    t = md.ApexTriggerMeta(api_name="T", object_name="Account", body=CLEAN)
    f = md.FlowMeta(api_name="F", process_type="AutoLaunchedFlow", trigger_object="Account")
    assert "D5.TRIGGER_AND_FLOW" in ids(rx.d5_automation_collision([t], [f]))
