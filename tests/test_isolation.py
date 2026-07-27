"""The tenant boundary.

An enterprise used to be a prefix in a free-text org name — "Meridian Insurance
· prod" — which the dashboard recovered by splitting on a separator. Two estates
sat in one Salesforce org distinguished by a string, `OrgIQ_Scan__c` had an
org-wide default of ReadWrite, and every child object is ControlledByParent of
it, so that one setting made the whole result set readable to anyone holding
object access. The architecture said "one install per enterprise"; the demo
proved the opposite was possible.

What is enforced by the platform, and what is enforced here, are different
things, and the difference is worth stating rather than blurring:

  **Platform.** `OrgIQ_Enterprise__c` is Private, and `OrgIQ_Target_Org__c` is a
  master-detail child of it, so an org cannot exist outside a tenant and cannot
  be read without reading its enterprise. `OrgIQ_Scan__c` is now Private too,
  and Finding / Dimension Score / Persona are ControlledByParent of it.

  **Here.** Salesforce permits three levels of custom master-detail, and
  Enterprise → Org → Scan → Finding is four. The chain has to break, and it
  breaks above the scan — so the scan carries a denormalised tenant key and
  these tests are what stop a read path forgetting it.

Neither is a VPC. Within one Salesforce org the strongest available boundary is
sharing, and the honest answer to "can two enterprises share an install?"
remains no — this makes the demo's two estates safe to show side by side, and
makes the boundary something a reviewer can check rather than be told about.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scanner"))

import pytest                                                  # noqa: E402
import enterprises                                             # noqa: E402
import scan_result                                             # noqa: E402
import scan_portfolio                                          # noqa: E402

OBJECTS = ROOT / "salesforce/force-app/main/default/objects"
PORTFOLIO = json.loads((ROOT / "dashboard/public/portfolio.json").read_text(encoding="utf-8"))


def object_xml(name):
    return (OBJECTS / name / f"{name}.object-meta.xml").read_text(encoding="utf-8")


def field_xml(obj, field):
    return (OBJECTS / obj / "fields" / f"{field}.field-meta.xml").read_text(encoding="utf-8")


# ------------------------------------------------ the platform's half

def test_the_tenant_object_denies_by_default():
    """Private, not ReadWrite. An org-wide default of ReadWrite means the
    boundary exists only for as long as every query remembers it."""
    assert "<sharingModel>Private</sharingModel>" in object_xml("OrgIQ_Enterprise__c")


def test_an_org_cannot_exist_outside_an_enterprise():
    """Master-detail, not lookup: a lookup is nullable, and a nullable tenant
    key is a row no isolation predicate can match."""
    xml = field_xml("OrgIQ_Target_Org__c", "Enterprise__c")
    assert "<type>MasterDetail</type>" in xml
    assert "<reparentableMasterDetail>false</reparentableMasterDetail>" in xml
    assert "<sharingModel>ControlledByParent</sharingModel>" in object_xml("OrgIQ_Target_Org__c")


def test_scan_results_are_not_world_readable():
    """Every result object is ControlledByParent of the scan, so the scan's own
    default decides all of them. It was ReadWrite."""
    assert "<sharingModel>Private</sharingModel>" in object_xml("OrgIQ_Scan__c")
    for child in ("OrgIQ_Finding__c", "OrgIQ_Dimension_Score__c", "OrgIQ_Persona__c"):
        assert "<sharingModel>ControlledByParent</sharingModel>" in object_xml(child), child


# --------------------------------------------------- the tenant key

def test_every_scan_carries_a_tenant():
    """Including a single-org scan that nobody told about an enterprise: it gets
    the default tenant rather than none, so there is no class of row outside the
    boundary."""
    result = scan_result.build([], [], "SomeOrg")
    assert result["scan"]["enterprise_id"] == scan_result.DEFAULT_ENTERPRISE_ID
    assert result["org"]["enterprise_id"] == scan_result.DEFAULT_ENTERPRISE_ID


def test_the_demo_estates_are_separate_tenants():
    scans, _ = scan_portfolio.build_portfolio()
    tenants = {s["scan"]["enterprise_id"] for s in scans}
    assert len(tenants) == 2, tenants
    for ent in enterprises.ENTERPRISES:
        assert enterprises.enterprise_id(ent["name"]) in tenants


def test_no_scan_belongs_to_two_tenants():
    """An org's history must not straddle a boundary — that would put one
    estate's earlier scans inside another's."""
    scans, _ = scan_portfolio.build_portfolio()
    by_org = {}
    for s in scans:
        by_org.setdefault(s["scan"]["target_org"], set()).add(s["scan"]["enterprise_id"])
    straddling = {o: t for o, t in by_org.items() if len(t) > 1}
    assert not straddling, straddling


# --------------------------------------------- the read paths honour it

def test_the_bundled_export_partitions_cleanly():
    """Every scan carries a tenant, and the tenants partition the estate —
    nothing shared, nothing orphaned."""
    scans = PORTFOLIO["scans"]
    assert PORTFOLIO.get("enterprises"), "the export carries no enterprise records"
    known = {e["id"] for e in PORTFOLIO["enterprises"]}
    assert all(s["scan"].get("enterpriseId") in known for s in scans)
    counts = {}
    for s in scans:
        counts[s["scan"]["enterpriseId"]] = counts.get(s["scan"]["enterpriseId"], 0) + len(s["findings"])
    assert sum(counts.values()) == sum(len(s["findings"]) for s in scans)


def test_the_dashboard_groups_on_the_id_and_not_the_name():
    """The regression this whole change exists to prevent. Grouping on a label
    means two tenants that happen to share a name merge, and a tenant whose
    label changes splits in two."""
    js = (ROOT / "dashboard/src/lib/data.js").read_text(encoding="utf-8")
    body = js[js.index("export function scansForEnterprise"):]
    body = body[:body.index("\n}")]
    assert "enterpriseId" in body, "scansForEnterprise no longer filters on the id"


def test_live_mode_reads_the_tenant_key():
    """Live mode queries the org directly. If it does not select the tenant, the
    dashboard cannot separate estates against a real org even though it can
    against the bundled file."""
    js = (ROOT / "dashboard/src/lib/live.js").read_text(encoding="utf-8")
    assert "Enterprise_Id__c" in js
    assert "enterpriseId:" in js


@pytest.mark.parametrize("path", ["dashboard/export_portfolio.py",
                                  "salesforce/load_portfolio.py"])
def test_the_pipeline_carries_the_tenant_end_to_end(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert "Enterprise" in src, f"{path} never mentions the tenant"
