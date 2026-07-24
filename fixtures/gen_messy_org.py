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

Writes CustomObject + CustomField metadata under <out>/main/default/objects,
plus Flow/Apex/trigger/permission-set material for D3–D5 and a reports/ +
dashboards/ folder that makes some fields provably in use and others provably
dead.
"""

import argparse
import re
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


# --- report/dashboard material: evidence of what the org actually LOOKS at ---
# Reports are the cheapest proof a field is load-bearing, so the split here is
# deliberate rather than incidental:
#   * MRR__c is pulled by more report/dashboard files than any other field, yet
#     carries no description — load-bearing AND unexplained, the worst
#     combination there is for an agent trying to ground itself.
#   * every cryptic twin of a semantic duplicate (Cust_Tier__c, Svc_Cd__c,
#     Email_Addr__c, Seg__c) and the tail of every numbered family
#     (Contact2/3, Tech2, Acct2/3/4) is referenced by NO report, so an
#     unreferenced-field rule has genuine positives instead of an empty set.
# Field names use the Object.Field form that ReportRefs keys on. Salesforce also
# emits Object$Field inside custom report types, but mixing both here would make
# the expected counts depend on which separators the parser happens to handle.

REPORTS = {
    # columns + filter + grouping + chart, all on Billing_Account__c
    "Billing_MRR_by_Tier": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>MRR by Customer Tier</name>
    <reportType>Billing_Account__c</reportType>
    <format>Summary</format>
    <scope>organization</scope>
    <columns>
        <field>Billing_Account__c.MRR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <columns>
        <field>Billing_Account__c.ARR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <columns>
        <field>Billing_Account__c.Credit_Balance__c</field>
    </columns>
    <groupingsDown>
        <field>Billing_Account__c.Customer_Tier__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsDown>
    <filter>
        <criteriaItems>
            <column>Billing_Account__c.Account_Status__c</column>
            <operator>equals</operator>
            <value>Active</value>
        </criteriaItems>
    </filter>
    <chart>
        <chartSummaries>
            <aggregate>Sum</aggregate>
            <axisBinding>y</axisBinding>
            <column>Billing_Account__c.MRR__c</column>
        </chartSummaries>
        <chartType>VerticalColumn</chartType>
        <groupingColumn>Billing_Account__c.Customer_Tier__c</groupingColumn>
        <size>Medium</size>
    </chart>
</Report>
""",
    # tabular: the collections team's daily worklist
    "Billing_Dunning_Watchlist": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Dunning Watchlist</name>
    <reportType>Billing_Account__c</reportType>
    <format>Tabular</format>
    <scope>organization</scope>
    <columns>
        <field>Billing_Account__c.Account_Status__c</field>
    </columns>
    <columns>
        <field>Billing_Account__c.Dunning_Flag__c</field>
    </columns>
    <columns>
        <field>Billing_Account__c.Credit_Balance__c</field>
    </columns>
    <columns>
        <field>Billing_Account__c.MRR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <columns>
        <field>Billing_Account__c.Billing_Cycle_Day__c</field>
    </columns>
    <filter>
        <criteriaItems>
            <column>Billing_Account__c.Dunning_Flag__c</column>
            <operator>equals</operator>
            <value>true</value>
        </criteriaItems>
    </filter>
</Report>
""",
    # grouped on a checkbox; touches Contact1 but never Contact2/3
    "Autopay_Adoption": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Autopay Adoption</name>
    <reportType>Billing_Account__c</reportType>
    <format>Summary</format>
    <scope>organization</scope>
    <columns>
        <field>Billing_Account__c.MRR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <columns>
        <field>Billing_Account__c.Contact1_Email__c</field>
    </columns>
    <groupingsDown>
        <field>Billing_Account__c.Auto_Pay_Enrolled__c</field>
        <sortOrder>Desc</sortOrder>
    </groupingsDown>
    <filter>
        <criteriaItems>
            <column>Billing_Account__c.Account_Status__c</column>
            <operator>notEqual</operator>
            <value>Closed</value>
        </criteriaItems>
    </filter>
</Report>
""",
    # matrix: grouping down AND across
    "Service_Orders_by_Status": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Service Orders by Status</name>
    <reportType>Service_Order__c</reportType>
    <format>Matrix</format>
    <scope>organization</scope>
    <columns>
        <field>Service_Order__c.Ordered_On__c</field>
    </columns>
    <columns>
        <field>Service_Order__c.Activated_On__c</field>
    </columns>
    <columns>
        <field>Service_Order__c.Service_Code__c</field>
    </columns>
    <columns>
        <field>Service_Order__c.Tech1_Assigned__c</field>
    </columns>
    <groupingsDown>
        <field>Service_Order__c.Provisioning_Status__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsDown>
    <groupingsAcross>
        <field>Service_Order__c.Order_Type__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsAcross>
</Report>
""",
    # date grouping — the field appears as a grouping, not a column
    "SLA_Breach_Trend": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>SLA Breach Trend</name>
    <reportType>Service_Order__c</reportType>
    <format>Summary</format>
    <scope>organization</scope>
    <columns>
        <field>Service_Order__c.SLA_Breached__c</field>
    </columns>
    <columns>
        <field>Service_Order__c.Provisioning_Status__c</field>
    </columns>
    <columns>
        <field>Service_Order__c.Service_Code__c</field>
    </columns>
    <groupingsDown>
        <dateGranularity>Month</dateGranularity>
        <field>Service_Order__c.Ordered_On__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsDown>
    <filter>
        <criteriaItems>
            <column>Service_Order__c.SLA_Breached__c</column>
            <operator>equals</operator>
            <value>true</value>
        </criteriaItems>
    </filter>
</Report>
""",
    # the only Legacy_Customer__c report — it uses the documented twin of each
    # duplicate pair and Acct1 only, leaving the rest of that object dead
    "Customer_Segment_Coverage": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Customer Segment Coverage</name>
    <reportType>Legacy_Customer__c</reportType>
    <format>Summary</format>
    <scope>organization</scope>
    <columns>
        <field>Legacy_Customer__c.Full_Name__c</field>
    </columns>
    <columns>
        <field>Legacy_Customer__c.Email_Address__c</field>
    </columns>
    <columns>
        <field>Legacy_Customer__c.Last_Verified__c</field>
    </columns>
    <columns>
        <field>Legacy_Customer__c.Acct1_Ref__c</field>
    </columns>
    <columns>
        <field>Legacy_Customer__c.Do_Not_Call__c</field>
    </columns>
    <groupingsDown>
        <field>Legacy_Customer__c.Segment__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsDown>
    <filter>
        <criteriaItems>
            <column>Legacy_Customer__c.Do_Not_Call__c</column>
            <operator>equals</operator>
            <value>false</value>
        </criteriaItems>
    </filter>
</Report>
""",
    # the exec view — another vote for MRR/ARR/Customer_Tier
    "Revenue_Exec_Summary": """<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://soap.sforce.com/2006/04/metadata">
    <name>Revenue Exec Summary</name>
    <reportType>Billing_Account__c</reportType>
    <format>Summary</format>
    <scope>organization</scope>
    <columns>
        <field>Billing_Account__c.MRR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <columns>
        <field>Billing_Account__c.ARR__c</field>
        <aggregateTypes>Sum</aggregateTypes>
    </columns>
    <groupingsDown>
        <field>Billing_Account__c.Customer_Tier__c</field>
        <sortOrder>Asc</sortOrder>
    </groupingsDown>
</Report>
""",
}

DASHBOARDS = {
    # references fields through component bindings, not through <columns>
    "Revenue_Health": """<?xml version="1.0" encoding="UTF-8"?>
<Dashboard xmlns="http://soap.sforce.com/2006/04/metadata">
    <title>Revenue Health</title>
    <dashboardType>LoggedInUser</dashboardType>
    <backgroundEndColor>#FFFFFF</backgroundEndColor>
    <backgroundFadeDirection>Diagonal</backgroundFadeDirection>
    <backgroundStartColor>#FFFFFF</backgroundStartColor>
    <textColor>#000000</textColor>
    <titleColor>#000000</titleColor>
    <titleSize>12</titleSize>
    <leftSection>
        <columnSize>Medium</columnSize>
        <components>
            <componentType>Bar</componentType>
            <header>MRR by tier</header>
            <groupingColumn>Billing_Account__c.Customer_Tier__c</groupingColumn>
            <dashboardFilterColumns>
                <column>Billing_Account__c.Account_Status__c</column>
            </dashboardFilterColumns>
            <legendPosition>Right</legendPosition>
            <report>OrgIQ_Ops/Billing_MRR_by_Tier</report>
        </components>
    </leftSection>
    <middleSection>
        <columnSize>Medium</columnSize>
        <components>
            <componentType>Table</componentType>
            <header>Top accounts</header>
            <dashboardTableColumn>
                <column>Billing_Account__c.MRR__c</column>
                <sortBy>ColumnDescending</sortBy>
            </dashboardTableColumn>
            <dashboardTableColumn>
                <column>Billing_Account__c.ARR__c</column>
            </dashboardTableColumn>
            <report>OrgIQ_Ops/Revenue_Exec_Summary</report>
        </components>
    </middleSection>
</Dashboard>
""",
    "Service_Operations": """<?xml version="1.0" encoding="UTF-8"?>
<Dashboard xmlns="http://soap.sforce.com/2006/04/metadata">
    <title>Service Operations</title>
    <dashboardType>LoggedInUser</dashboardType>
    <backgroundEndColor>#FFFFFF</backgroundEndColor>
    <backgroundFadeDirection>Diagonal</backgroundFadeDirection>
    <backgroundStartColor>#FFFFFF</backgroundStartColor>
    <textColor>#000000</textColor>
    <titleColor>#000000</titleColor>
    <titleSize>12</titleSize>
    <leftSection>
        <columnSize>Medium</columnSize>
        <components>
            <componentType>Donut</componentType>
            <header>Orders by provisioning status</header>
            <groupingColumn>Service_Order__c.Provisioning_Status__c</groupingColumn>
            <dashboardFilterColumns>
                <column>Service_Order__c.Order_Type__c</column>
            </dashboardFilterColumns>
            <report>OrgIQ_Ops/Service_Orders_by_Status</report>
        </components>
    </leftSection>
    <rightSection>
        <columnSize>Medium</columnSize>
        <components>
            <componentType>Metric</componentType>
            <header>SLA breaches this month</header>
            <dashboardTableColumn>
                <column>Service_Order__c.SLA_Breached__c</column>
            </dashboardTableColumn>
            <report>OrgIQ_Ops/SLA_Breach_Trend</report>
        </components>
    </rightSection>
</Dashboard>
""",
}

# Reports and dashboards live inside a folder in a real SFDX tree; the folder
# metadata sits beside the directory and must NOT be mistaken for a report.
REPORT_FOLDER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ReportFolder xmlns="http://soap.sforce.com/2006/04/metadata">
    <accessType>Public</accessType>
    <name>OrgIQ Ops</name>
    <publicFolderAccess>ReadWrite</publicFolderAccess>
</ReportFolder>
"""

DASHBOARD_FOLDER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DashboardFolder xmlns="http://soap.sforce.com/2006/04/metadata">
    <accessType>Public</accessType>
    <name>OrgIQ Ops</name>
    <publicFolderAccess>ReadWrite</publicFolderAccess>
</DashboardFolder>
"""

FOLDER = "OrgIQ_Ops"

_REF_RE = re.compile(r"\b(\w+__c)\.(\w+__c)\b")


def _ref_counts() -> dict:
    """Object.Field -> number of report/dashboard FILES that reference it.

    Derived from the XML above rather than hand-maintained, so the summary the
    generator prints can never drift from what it actually wrote. Raises if a
    report points at a field the fixture does not define — a silent typo would
    turn a "load-bearing" field into a false unreferenced positive.
    """
    counts = {}
    for xml in list(REPORTS.values()) + list(DASHBOARDS.values()):
        for ref in sorted({f"{obj}.{fld}" for obj, fld in _REF_RE.findall(xml)}):
            counts[ref] = counts.get(ref, 0) + 1
    known = {f"{obj}.{fld[0]}" for obj, (_, flds) in OBJECTS.items() for fld in flds}
    unknown = sorted(set(counts) - known)
    if unknown:
        raise SystemExit(f"fixture reports reference undefined fields: {unknown}")
    return counts


def _write_reports(base: Path) -> tuple:
    """Write the report/dashboard folders. Returns (n_reports, n_dashboards)."""
    rdir = base / "reports"
    (rdir / FOLDER).mkdir(parents=True, exist_ok=True)
    (rdir / f"{FOLDER}.reportFolder-meta.xml").write_text(REPORT_FOLDER_XML)
    for name, xml in REPORTS.items():
        (rdir / FOLDER / f"{name}.report-meta.xml").write_text(xml)

    ddir = base / "dashboards"
    (ddir / FOLDER).mkdir(parents=True, exist_ok=True)
    (ddir / f"{FOLDER}.dashboardFolder-meta.xml").write_text(DASHBOARD_FOLDER_XML)
    for name, xml in DASHBOARDS.items():
        (ddir / FOLDER / f"{name}.dashboard-meta.xml").write_text(xml)

    return len(REPORTS), len(DASHBOARDS)


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

    default = Path(a.out) / "main" / "default"
    n_extra = _write_extras(default)
    n_rep, n_dash = _write_reports(default)

    counts = _ref_counts()
    # tie-break on name so the "load-bearing" field named here is stable
    top, top_n = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    print(f"wrote {n_obj} objects, {n_fld} fields, {n_extra} flow/apex/trigger/permset "
          f"files, {n_rep} reports, {n_dash} dashboards under {default}")
    print(f"  report refs: {len(counts)} of {n_fld} fields referenced, "
          f"{n_fld - len(counts)} referenced by nothing; "
          f"most-referenced {top} ({top_n} files)")


if __name__ == "__main__":
    main()
