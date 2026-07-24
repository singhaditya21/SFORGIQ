"""Metadata parsing and the Apex body heuristics D5 relies on."""

import metadata as md


# ------------------------------------------------------------- body heuristics

DIRTY_TRIGGER = """
trigger AcctTrigger on Account (after insert) {
    for (Account a : Trigger.new) {
        List<Contact> cs = [SELECT Id FROM Contact WHERE AccountId = :a.Id];
        Contact c = new Contact();
        insert c;
    }
}
"""

CLEAN_TRIGGER = """
trigger AcctTrigger on Account (after insert) {
    if (AcctHandler.hasRun) return;
    List<Contact> cs = [SELECT Id FROM Contact];
    AcctHandler.handle(Trigger.new);
}
"""


def test_dml_and_soql_inside_a_loop_are_detected():
    assert md.dml_in_loop(DIRTY_TRIGGER) == 1
    assert md.soql_in_loop(DIRTY_TRIGGER) == 1


def test_dml_and_soql_outside_a_loop_are_not_flagged():
    assert md.dml_in_loop(CLEAN_TRIGGER) == 0
    assert md.soql_in_loop(CLEAN_TRIGGER) == 0


def test_recursion_guard_detection():
    assert md.has_recursion_guard(CLEAN_TRIGGER) is True
    assert md.has_recursion_guard(DIRTY_TRIGGER) is False
    assert md.has_recursion_guard("private static Boolean alreadyDone = false;") is True


# ------------------------------------------------------------------ parsers

def test_parses_flow_apex_trigger_and_permission_set(tmp_path):
    d = tmp_path / "main" / "default"
    (d / "flows").mkdir(parents=True)
    (d / "flows" / "After_Save.flow-meta.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
        '<label>After Save</label><processType>AutoLaunchedFlow</processType>'
        '<status>Draft</status>'
        '<start><object>Account</object><recordTriggerType>Update</recordTriggerType></start>'
        '</Flow>')
    (d / "classes").mkdir(parents=True)
    (d / "classes" / "Svc.cls").write_text(
        "public with sharing class Svc {\n  @InvocableMethod\n  public static void go() {}\n}")
    (d / "triggers").mkdir(parents=True)
    (d / "triggers" / "AcctTrigger.trigger").write_text(DIRTY_TRIGGER)
    (d / "permissionsets").mkdir(parents=True)
    (d / "permissionsets" / "Agent.permissionset-meta.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">'
        '<label>Agent</label>'
        '<userPermissions><enabled>true</enabled><name>ModifyAllData</name></userPermissions>'
        '<userPermissions><enabled>false</enabled><name>ViewAllData</name></userPermissions>'
        '<objectPermissions><object>Account</object><allowDelete>true</allowDelete>'
        '<modifyAllRecords>true</modifyAllRecords></objectPermissions>'
        '</PermissionSet>')

    meta = md.parse_project(tmp_path)

    flow = meta.flows[0]
    assert flow.is_autolaunched and flow.status == "Draft"
    assert flow.is_record_triggered and flow.trigger_object == "Account"

    cls = meta.apex[0]
    assert cls.invocable_methods == 1
    assert cls.invocable_without_label == 1
    assert cls.sharing == "with sharing"
    assert cls.is_test is False

    trg = meta.triggers[0]
    assert trg.object_name == "Account" and trg.api_name == "AcctTrigger"

    ps = meta.permission_sets[0]
    assert ps.has_perm("ModifyAllData") is True
    assert ps.has_perm("ViewAllData") is False      # enabled=false must not count
    assert ps.object_perms[0].modify_all is True


def test_assessable_dims_reflects_available_inputs():
    empty = md.OrgMetadata()
    assert empty.assessable_dims() == set()

    with_perms = md.OrgMetadata(permission_sets=[md.PermissionSetMeta(api_name="P")])
    assert with_perms.assessable_dims() == {"D4"}

    with_data = md.OrgMetadata(record_stats=[md.RecordStats(object_name="Account")])
    assert with_data.assessable_dims() == {"D2"}
