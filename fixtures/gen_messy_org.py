#!/usr/bin/env python3
"""
Generate a deliberately-messy SFDX metadata fixture — the D1 "defect catalogue"
the PRD calls for (§6.3). Deterministic and curated, not random, so the scan it
produces is stable and reviewable.

It models a plausible ~15-year-old enterprise CRM: a mix of well-documented
fields and every D1 defect class the scanner detects — missing descriptions,
label-restating descriptions, cryptic/abbreviated names, numbered field
families, and semantic duplicates.

    python3 fixtures/gen_messy_org.py --out fixtures/messy_org/force-app

Writes CustomObject + CustomField metadata under <out>/main/default/objects.
"""

import argparse
from pathlib import Path

# (api_name, label, type, description)  — description "" means missing.
OBJECTS = {
    "Billing_Account__c": ("Billing Account", [
        ("Account_Status__c", "Account Status", "Picklist",
         "Current lifecycle status of the billing account (Active, Dunning, Closed)."),
        ("Billing_Cycle_Day__c", "Billing Cycle Day", "Number",
         "Day of the month on which the recurring invoice is generated."),
        ("MRR__c", "MRR", "Currency", ""),                       # missing + cryptic acronym
        ("ARR__c", "ARR", "Currency", ""),                       # missing + cryptic acronym
        ("Cust_Tier__c", "Cust Tier", "Text", ""),               # cryptic (abbrev) + missing
        ("Customer_Tier__c", "Customer Tier", "Text",
         "Customer value tier used for support SLAs (Bronze, Silver, Gold, Platinum)."),  # dup of Cust_Tier
        ("Dunning_Flag__c", "Dunning Flag", "Checkbox",
         "Dunning Flag"),                                        # low-info: restates label
        ("Contact1_Email__c", "Contact 1 Email", "Email", ""),   # numbered family
        ("Contact2_Email__c", "Contact 2 Email", "Email", ""),
        ("Contact3_Email__c", "Contact 3 Email", "Email", ""),
        ("Legacy_Bill_Id__c", "Legacy Bill Id", "Text", ""),     # missing
        ("Auto_Pay_Enrolled__c", "Auto Pay Enrolled", "Checkbox",
         "True when the account is enrolled in automatic payment collection."),
        ("Pmt_Mthd__c", "Pmt Mthd", "Text", ""),                 # cryptic vowelless/abbrev + missing
        ("Credit_Balance__c", "Credit Balance", "Currency",
         "Unapplied credit currently held on the account, in account currency."),
    ]),
    "Service_Order__c": ("Service Order", [
        ("Order_Type__c", "Order Type", "Picklist",
         "Kind of service order (New, Upgrade, Downgrade, Disconnect)."),
        ("Provisioning_Status__c", "Provisioning Status", "Picklist",
         "Where the order sits in the provisioning workflow."),
        ("Svc_Cd__c", "Svc Cd", "Text", ""),                     # cryptic + missing
        ("Service_Code__c", "Service Code", "Text",
         "Catalogue code identifying the provisioned service."),  # dup of Svc_Cd (svc->service, cd->code)
        ("Status__c", "Status", "Text", "Status"),               # low-info + generic
        ("Ordered_On__c", "Ordered On", "Date",
         "Date the customer placed the order."),
        ("Activated_On__c", "Activated On", "Date",
         "Date the service was activated in the network."),
        ("Tech1_Assigned__c", "Tech 1 Assigned", "Text", ""),    # numbered family
        ("Tech2_Assigned__c", "Tech 2 Assigned", "Text", ""),
        ("Rbk__c", "Rbk", "Text", ""),                           # cryptic vowelless + missing
        ("SLA_Breached__c", "SLA Breached", "Checkbox",
         "True if the provisioning SLA was missed for this order."),
        ("Notes__c", "Notes", "LongTextArea",
         "Free-form dispatch and provisioning notes entered by agents."),
        ("Priority_Level__c", "Priority Level", "Number", ""),   # missing
    ]),
    "Legacy_Customer__c": ("Legacy Customer", [
        ("Full_Name__c", "Full Name", "Text",
         "Customer's full legal name as captured at onboarding."),
        ("Cust_Nm__c", "Cust Nm", "Text", ""),                   # cryptic + missing (dup-ish of Full Name? no)
        ("Email_Addr__c", "Email Addr", "Email", ""),            # abbrev + missing
        ("Email_Address__c", "Email Address", "Email",
         "Primary contact email address."),                      # dup of Email_Addr
        ("Seg__c", "Seg", "Text", ""),                           # cryptic short + missing
        ("Segment__c", "Segment", "Text", "Segment"),            # low-info + dup of Seg
        ("Region_Cd__c", "Region Cd", "Text", ""),               # cryptic abbrev + missing
        ("Acct1_Ref__c", "Acct 1 Ref", "Text", ""),             # numbered family
        ("Acct2_Ref__c", "Acct 2 Ref", "Text", ""),
        ("Acct3_Ref__c", "Acct 3 Ref", "Text", ""),
        ("Acct4_Ref__c", "Acct 4 Ref", "Text", ""),
        ("X_Flag__c", "X Flag", "Checkbox", ""),                 # cryptic very short + missing
        ("Do_Not_Call__c", "Do Not Call", "Checkbox",
         "Customer has opted out of outbound sales calls."),
        ("Last_Verified__c", "Last Verified", "Date",
         "Date the customer's contact details were last confirmed."),
        ("Migration_Batch__c", "Migration Batch", "Text",
         "Identifier of the data-migration batch that created this record."),
    ]),
}

OBJECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>{label}</label>
    <pluralLabel>{label}s</pluralLabel>
    <deploymentStatus>Deployed</deploymentStatus>
    <sharingModel>ReadWrite</sharingModel>
    <nameField>
        <label>Name</label>
        <type>Text</type>
    </nameField>
</CustomObject>
"""

FIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>{api}</fullName>
    <label>{label}</label>
    <type>{type}</type>{desc}
</CustomField>
"""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --- D3/D4/D5 material: real Flow / Apex / trigger / permission-set files -----
# Each carries a defect the corresponding rule pack genuinely detects.

FLOWS = {
    # autolaunched but undocumented -> D3.UNDOCUMENTED_ACTION
    "Create_Service_Order": """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Create Service Order</label>
    <processType>AutoLaunchedFlow</processType>
    <status>Active</status>
</Flow>
""",
    # draft -> D3.INACTIVE_ACTION
    "Close_Dormant_Accounts": """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Close Dormant Accounts</label>
    <description>Closes billing accounts with no activity for 24 months.</description>
    <processType>AutoLaunchedFlow</processType>
    <status>Draft</status>
</Flow>
""",
    # record-triggered on the same object as a trigger -> D5.TRIGGER_AND_FLOW
    "Billing_Account_After_Save": """<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Billing Account After Save</label>
    <description>Recalculates balance roll-ups after a billing account is saved.</description>
    <processType>AutoLaunchedFlow</processType>
    <status>Active</status>
    <start>
        <object>Billing_Account__c</object>
        <recordTriggerType>CreateAndUpdate</recordTriggerType>
    </start>
</Flow>
""",
}

APEX = {
    # invocable, no label, and no test class references it
    # -> D3.UNDOCUMENTED_ACTION + D3.APEX_NO_TESTS
    "BillingService": """public with sharing class BillingService {
    @InvocableMethod
    public static List<String> recalculate(List<Id> accountIds) {
        List<String> out = new List<String>();
        for (Id accountId : accountIds) {
            out.add(String.valueOf(accountId));
        }
        return out;
    }
}
""",
}

TRIGGERS = {
    # DML + SOQL inside a loop, no recursion guard -> D5.DML_IN_LOOP,
    # D5.SOQL_IN_LOOP, D5.NO_RECURSION_GUARD
    "BillingAccountTrigger": """trigger BillingAccountTrigger on Billing_Account__c (after insert, after update) {
    for (Billing_Account__c acct : Trigger.new) {
        List<Service_Order__c> orders = [SELECT Id FROM Service_Order__c WHERE Id = :acct.Id];
        Service_Order__c so = new Service_Order__c();
        insert so;
    }
}
""",
    # a second trigger on the same object -> D5.MULTIPLE_TRIGGERS
    "BillingAccountAuditTrigger": """trigger BillingAccountAuditTrigger on Billing_Account__c (before update) {
    System.debug('audit');
}
""",
}

PERMISSION_SETS = {
    # Modify All Data (Critical) + View All Data + over-broad object rights
    "Agent_Integration": """<?xml version="1.0" encoding="UTF-8"?>
<PermissionSet xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Agent Integration</label>
    <hasActivationRequired>false</hasActivationRequired>
    <userPermissions>
        <enabled>true</enabled>
        <name>ModifyAllData</name>
    </userPermissions>
    <userPermissions>
        <enabled>true</enabled>
        <name>ViewAllData</name>
    </userPermissions>
    <objectPermissions>
        <object>Billing_Account__c</object>
        <allowRead>true</allowRead>
        <allowEdit>true</allowEdit>
        <allowDelete>true</allowDelete>
        <modifyAllRecords>true</modifyAllRecords>
        <viewAllRecords>true</viewAllRecords>
    </objectPermissions>
    <objectPermissions>
        <object>Legacy_Customer__c</object>
        <allowRead>true</allowRead>
        <allowEdit>true</allowEdit>
        <allowDelete>true</allowDelete>
        <modifyAllRecords>false</modifyAllRecords>
        <viewAllRecords>false</viewAllRecords>
    </objectPermissions>
</PermissionSet>
""",
}


def _write_extras(base: Path) -> int:
    """Write the Flow/Apex/trigger/permission-set files. Returns file count."""
    n = 0
    for name, xml in FLOWS.items():
        d = base / "flows"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.flow-meta.xml").write_text(xml); n += 1
    for name, src in APEX.items():
        d = base / "classes"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.cls").write_text(src); n += 1
    for name, src in TRIGGERS.items():
        d = base / "triggers"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.trigger").write_text(src); n += 1
    for name, xml in PERMISSION_SETS.items():
        d = base / "permissionsets"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.permissionset-meta.xml").write_text(xml); n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fixtures/messy_org/force-app")
    a = ap.parse_args()

    base = Path(a.out) / "main" / "default" / "objects"
    n_obj = n_fld = 0
    for obj, (label, fields) in OBJECTS.items():
        odir = base / obj
        (odir / "fields").mkdir(parents=True, exist_ok=True)
        (odir / f"{obj}.object-meta.xml").write_text(OBJECT_XML.format(label=label))
        n_obj += 1
        for api, flabel, ftype, desc in fields:
            desc_xml = f"\n    <description>{_esc(desc)}</description>" if desc else ""
            (odir / "fields" / f"{api}.field-meta.xml").write_text(
                FIELD_XML.format(api=api, label=_esc(flabel), type=ftype, desc=desc_xml))
            n_fld += 1

    n_extra = _write_extras(Path(a.out) / "main" / "default")
    print(f"wrote {n_obj} objects, {n_fld} fields, {n_extra} flow/apex/trigger/permset "
          f"files under {Path(a.out) / 'main' / 'default'}")


if __name__ == "__main__":
    main()
