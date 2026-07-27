#!/usr/bin/env python3
"""
D2–D5 rule packs.

These run on parsed metadata (scanner/metadata.py), not on invented signals:
D3 reads Flows and Apex, D4 reads permission sets, D5 reads triggers and
record-triggered Flows. D2 needs record-level data, which a bare SFDX directory
does not carry — it only runs when RecordStats are supplied (org mode).

A dimension with no inputs is simply not assessed; see OrgMetadata.assessable_dims.
"""

from __future__ import annotations

from collections import defaultdict

import metadata as md
from orgiq_spike import Finding


def _f(rule_id, dim, sev, conf, component, evidence, detail=""):
    return Finding(rule_id, dim, sev, conf, component, evidence, detail)


# ------------------------------------------------- D2 Data Foundation

# Thresholds are provisional, like the effort table.
FILL_FLOOR = 0.60
STALE_CEIL = 0.40
DUP_CEIL = 0.06


def d2_data_foundation(stats) -> list:
    """Can the data be trusted enough to ground an agent on it?"""
    out = []
    for s in stats:
        if s.fill_rate < FILL_FLOOR:
            out.append(_f("D2.LOW_FILL_RATE", "D2",
                          "High" if s.fill_rate < 0.40 else "Medium", "Medium",
                          s.object_name,
                          f"key fields populated on only {s.fill_rate * 100:.0f}% of records"))
        if s.stale_ratio > STALE_CEIL:
            out.append(_f("D2.STALE_DATA", "D2", "Medium", "Medium", s.object_name,
                          f"{s.stale_ratio * 100:.0f}% of records not updated in 24 months"))
        # A duplicate rate is only a claim about the data when the key it was
        # grouped on identifies a business entity. Where the object's name is a
        # category — a role, a line-item type, a junction label — every repeat is
        # correct, and the collector says so by reporting a uniqueness below the
        # threshold. Guarded here as well as at collection: this rule is what
        # emits a High-severity ticket telling someone to merge records, and a
        # stat arriving from anywhere else must not be able to trigger it.
        if (s.duplicate_rate > DUP_CEIL
                and getattr(s, "key_uniqueness", 1.0) >= md.MIN_KEY_UNIQUENESS):
            out.append(_f("D2.DUPLICATE_RECORDS", "D2",
                          "High" if s.duplicate_rate > 0.15 else "Medium", "Medium",
                          s.object_name,
                          f"~{s.duplicate_rate * 100:.0f}% duplicate records detected"))
    return out


# ------------------------------------------------- D3 Action Surface

def d3_action_surface(flows, apex) -> list:
    """Can the agent safely *do* anything, and can a planner pick the right action?"""
    out = []
    callable_flows = [f for f in flows if f.is_autolaunched]
    invocable_classes = [c for c in apex if c.invocable_methods > 0]

    if not callable_flows and not invocable_classes:
        out.append(_f("D3.NO_SAFE_ACTIONS", "D3", "High", "High", "org",
                      "no autolaunched flow or @InvocableMethod exists for an agent to call"))

    for f in callable_flows:
        if not f.description.strip():
            out.append(_f("D3.UNDOCUMENTED_ACTION", "D3", "Medium", "High", f.api_name,
                          "autolaunched flow has no description for the planner to match on"))
        if f.status and f.status != "Active":
            out.append(_f("D3.INACTIVE_ACTION", "D3", "Medium", "High", f.api_name,
                          f"flow is {f.status} — it cannot be invoked"))

    for c in invocable_classes:
        if c.invocable_without_label:
            out.append(_f("D3.UNDOCUMENTED_ACTION", "D3", "Medium", "High", f"{c.api_name}.cls",
                          f"{c.invocable_without_label} @InvocableMethod(s) declared without a label"))

    # An invocable class with no test anywhere referencing it.
    tests = [c for c in apex if c.is_test]
    for c in invocable_classes:
        if not any(c.api_name in t.body for t in tests):
            out.append(_f("D3.APEX_NO_TESTS", "D3", "Medium", "Medium", f"{c.api_name}.cls",
                          "agent-invocable Apex has no test class referencing it"))
    return out


# ------------------------------------------- D4 Permission Blast Radius

def d4_blast_radius(permission_sets) -> list:
    """What can the agent reach if something goes wrong?"""
    out = []
    for ps in permission_sets:
        if ps.has_perm("ModifyAllData"):
            out.append(_f("D4.MODIFY_ALL_DATA", "D4", "Critical", "High", ps.api_name,
                          "permission set grants Modify All Data"))
        if ps.has_perm("ViewAllData"):
            out.append(_f("D4.VIEW_ALL_DATA", "D4", "High", "High", ps.api_name,
                          "permission set grants View All Data"))
        for op in ps.object_perms:
            if op.modify_all or op.view_all:
                out.append(_f("D4.WIDE_OBJECT_ACCESS", "D4", "Medium", "High",
                              f"{ps.api_name}:{op.object_name}",
                              "grants Modify All / View All Records on the object"))
            elif op.allow_delete:
                out.append(_f("D4.DELETE_GRANTED", "D4", "Medium", "Medium",
                              f"{ps.api_name}:{op.object_name}",
                              "grants delete — rarely needed by an agent"))
    return out


# ---------------------------------------- D5 Automation Collision

def d5_automation_collision(triggers, flows) -> list:
    """Will the agent's writes set off cascading automation?"""
    out = []

    by_object = defaultdict(list)
    for t in triggers:
        if t.object_name:
            by_object[t.object_name].append(t)
    for obj, ts in by_object.items():
        if len(ts) > 1:
            out.append(_f("D5.MULTIPLE_TRIGGERS", "D5", "Medium", "High", obj,
                          f"{len(ts)} triggers on one object with undefined execution order",
                          " | ".join(sorted(t.api_name for t in ts))))

    for t in triggers:
        n = md.dml_in_loop(t.body)
        if n:
            out.append(_f("D5.DML_IN_LOOP", "D5", "High", "Medium", t.api_name,
                          f"{n} DML statement(s) inside a loop — bulk writes will hit limits"))
        n = md.soql_in_loop(t.body)
        if n:
            out.append(_f("D5.SOQL_IN_LOOP", "D5", "High", "Medium", t.api_name,
                          f"{n} SOQL quer(ies) inside a loop"))
        if not md.has_recursion_guard(t.body):
            out.append(_f("D5.NO_RECURSION_GUARD", "D5", "Medium", "Low", t.api_name,
                          "no static recursion guard — an agent write can re-fire automation"))

    # A trigger and a record-triggered flow on the same object is the classic
    # ordering-collision setup.
    flow_objs = {f.trigger_object for f in flows if f.is_record_triggered}
    for obj in sorted(flow_objs & set(by_object)):
        out.append(_f("D5.TRIGGER_AND_FLOW", "D5", "Medium", "High", obj,
                      "both an Apex trigger and a record-triggered flow run on this object"))
    return out


def all_findings(meta: md.OrgMetadata) -> list:
    """Every D2–D5 finding available from the supplied metadata."""
    return (d2_data_foundation(meta.record_stats)
            + d3_action_surface(meta.flows, meta.apex)
            + d4_blast_radius(meta.permission_sets)
            + d5_automation_collision(meta.triggers, meta.flows))
