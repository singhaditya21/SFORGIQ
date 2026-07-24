#!/usr/bin/env python3
"""
D2–D5 rule packs for the OrgIQ *demo portfolio*.

The real source-mode scanner (orgiq_spike.py) assesses D1 only, from field
metadata. The other four dimensions need signals a bare SFDX directory doesn't
carry — record-quality stats (D2), Flow/Apex/action metadata (D3), permission
grants (D4), and the automation graph (D5). Rather than fake those for the real
scanner, this module generates *synthetic-but-correlated* signals for the
fictional portfolio orgs and runs representative rules over them, so the demo
can show all five dimensions end to end.

Signals scale with each org's `defect_ratio`, so a messy D1 org also tends to
carry data, permission and automation debt. Deterministic (seeded); the caller
passes its own random.Random.
"""

from orgiq_spike import Finding


def _f(rule_id, dim, sev, conf, component, evidence, detail=""):
    return Finding(rule_id, dim, sev, conf, component, evidence, detail)


def _d2(objects, r, rnd):
    """D2 Data Foundation — is the data trustworthy enough to ground on?"""
    out = []
    for obj in objects[:3]:
        fill = max(0.05, 1 - r * rnd.uniform(0.5, 1.25))
        stale = min(0.95, r * rnd.uniform(0.4, 1.1))
        dup = min(0.5, r * rnd.uniform(0.05, 0.35))
        if fill < 0.6:
            out.append(_f("D2.LOW_FILL_RATE", "D2",
                          "High" if fill < 0.4 else "Medium", "Medium", obj,
                          f"key fields populated on only {fill*100:.0f}% of records"))
        if stale > 0.4:
            out.append(_f("D2.STALE_DATA", "D2", "Medium", "Medium", obj,
                          f"{stale*100:.0f}% of records not updated in 24 months"))
        if dup > 0.06:
            out.append(_f("D2.DUPLICATE_RECORDS", "D2",
                          "High" if dup > 0.15 else "Medium", "Medium", obj,
                          f"~{dup*100:.0f}% duplicate records detected"))
    return out


def _d3(objects, r, rnd):
    """D3 Action Surface — can the agent safely *do* anything?"""
    out = []
    invocable = 0 if r > 0.5 and rnd.random() < 0.6 else rnd.randint(1, 6)
    if invocable == 0:
        out.append(_f("D3.NO_SAFE_ACTIONS", "D3", "High", "Medium", "org",
                      "no invocable, bulk-safe actions exposed for an agent to call"))
    for i in range(int(r * rnd.uniform(4, 9))):
        out.append(_f("D3.UNDOCUMENTED_ACTION", "D3", "Medium", "Medium",
                      f"{rnd.choice(objects)}.Action{i+1}",
                      "invocable action has no description for the planner to match on"))
    for i in range(int(r * rnd.uniform(2, 5))):
        out.append(_f("D3.APEX_NO_TESTS", "D3", "Medium", "High",
                      f"{rnd.choice(['Account','Order','Case','Billing'])}Service{i+1}.cls",
                      "Apex invoked by automation has no test coverage"))
    return out


def _d4(objects, r, rnd):
    """D4 Permission Blast Radius — what can it reach if something goes wrong?"""
    out = []
    if r > 0.55 and rnd.random() < 0.6:
        out.append(_f("D4.MODIFY_ALL_DATA", "D4", "Critical", "High",
                      f"PermSet: {rnd.choice(['Ops','Integration','Service'])}_Agent",
                      "the agent's permission set grants Modify All Data"))
    if r > 0.35 and rnd.random() < 0.7:
        out.append(_f("D4.VIEW_ALL_DATA", "D4", "High", "High",
                      f"PermSet: {rnd.choice(['Ops','Support','Sales'])}_Agent",
                      "the agent's permission set grants View All Data"))
    for obj in objects[:int(r * rnd.uniform(3, 7))]:
        out.append(_f("D4.WIDE_OBJECT_ACCESS", "D4", "Medium", "Medium", obj,
                      "agent profile has edit access far beyond its task scope"))
    return out


def _d5(objects, r, rnd):
    """D5 Automation Collision — will its writes trigger cascading chaos?"""
    out = []
    for i in range(int(r * rnd.uniform(2, 5))):
        obj = rnd.choice(objects)
        out.append(_f("D5.DML_IN_LOOP", "D5", "High", "High",
                      f"{obj[:-3]}Trigger", "DML inside a loop — will hit governor limits on bulk writes",
                      f"call site {i+1}"))
    for obj in objects[:int(r * rnd.uniform(1, 4))]:
        out.append(_f("D5.MULTIPLE_TRIGGERS", "D5", "Medium", "Medium", obj,
                      "multiple triggers on one object with undefined execution order"))
    for i in range(int(r * rnd.uniform(2, 5))):
        obj = rnd.choice(objects)
        out.append(_f("D5.NO_RECURSION_GUARD", "D5", "Medium", "Medium",
                      f"{obj[:-3]}Trigger", "no recursion guard — an agent write can re-fire automation",
                      f"handler {i+1}"))
    return out


def dimension_findings(objects, defect_ratio, rnd):
    """All D2–D5 findings for one org. `objects` is the list of that org's
    object API names (so findings reference real components)."""
    objs = objects or ["Account__c"]
    return _d2(objs, defect_ratio, rnd) + _d3(objs, defect_ratio, rnd) \
        + _d4(objs, defect_ratio, rnd) + _d5(objs, defect_ratio, rnd)
