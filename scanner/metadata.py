#!/usr/bin/env python3
"""
Metadata model + SFDX parsers for the dimensions beyond D1.

D1 needs only field metadata. D3/D4/D5 need Flows, Apex, triggers and permission
sets — this module turns those files into plain dataclasses, so the rule packs
operate on parsed structures rather than on file paths. The same structures can
be built in memory (by the portfolio generator), which means one set of rules
serves both a real SFDX project and the synthetic demo corpus.

Body analysis (DML in loops, recursion guards) is deliberately heuristic and
said to be so — it is a spike, not a compiler.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field as dc_field
from pathlib import Path

NS = {"sf": "http://soap.sforce.com/2006/04/metadata"}


# ------------------------------------------------------------------ model

@dataclass
class FlowMeta:
    api_name: str
    label: str = ""
    description: str = ""
    process_type: str = ""          # AutoLaunchedFlow | Flow | ...
    status: str = "Active"          # Active | Draft | Obsolete
    trigger_object: str = ""        # set for record-triggered flows
    record_trigger_type: str = ""   # Create | Update | CreateAndUpdate | Delete
    path: str = ""

    @property
    def is_autolaunched(self) -> bool:
        return self.process_type == "AutoLaunchedFlow"

    @property
    def is_record_triggered(self) -> bool:
        return bool(self.trigger_object)


@dataclass
class ApexClassMeta:
    api_name: str
    body: str = ""
    sharing: str = ""               # with sharing | without sharing | inherited | ""
    path: str = ""

    @property
    def is_test(self) -> bool:
        return "@istest" in self.body.lower()

    @property
    def invocable_methods(self) -> int:
        return len(re.findall(r"@InvocableMethod", self.body, re.I))

    @property
    def invocable_without_label(self) -> int:
        # @InvocableMethod with no label= — the planner has nothing to match on.
        return len([m for m in re.findall(r"@InvocableMethod([^\n]*)", self.body, re.I)
                    if "label" not in m.lower()])


@dataclass
class ApexTriggerMeta:
    api_name: str
    object_name: str = ""
    events: list = dc_field(default_factory=list)
    body: str = ""
    path: str = ""


@dataclass
class ObjectPerm:
    object_name: str
    allow_edit: bool = False
    allow_delete: bool = False
    modify_all: bool = False
    view_all: bool = False


@dataclass
class PermissionSetMeta:
    api_name: str
    label: str = ""
    user_permissions: list = dc_field(default_factory=list)   # names of enabled perms
    object_perms: list = dc_field(default_factory=list)       # ObjectPerm
    path: str = ""

    def has_perm(self, name: str) -> bool:
        return name in self.user_permissions


@dataclass
class RecordStats:
    """Record-level signal for D2. Only org mode can supply this — a bare SFDX
    directory carries no data."""
    object_name: str
    fill_rate: float = 1.0        # 0..1, key fields populated
    stale_ratio: float = 0.0      # 0..1, not updated in 24 months
    duplicate_rate: float = 0.0   # 0..1


@dataclass
class OrgMetadata:
    """Everything the D3/D4/D5 packs need. Empty lists mean 'not available',
    which is what drives the assessed/not-assessed decision."""
    flows: list = dc_field(default_factory=list)
    apex: list = dc_field(default_factory=list)
    triggers: list = dc_field(default_factory=list)
    permission_sets: list = dc_field(default_factory=list)
    record_stats: list = dc_field(default_factory=list)

    def assessable_dims(self) -> set:
        """Which dimensions actually have inputs. D1 is decided by the caller
        (it needs fields, which the D1 scanner already parses)."""
        dims = set()
        if self.record_stats:
            dims.add("D2")
        if self.flows or self.apex:
            dims.add("D3")
        if self.permission_sets:
            dims.add("D4")
        if self.triggers or any(f.is_record_triggered for f in self.flows):
            dims.add("D5")
        return dims


# ---------------------------------------------------------------- parsers

def _text(root, tag: str) -> str:
    el = root.find(f"sf:{tag}", NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_flows(root: Path) -> list:
    out = []
    for p in root.rglob("*.flow-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        start = r.find("sf:start", NS)
        out.append(FlowMeta(
            api_name=p.name.replace(".flow-meta.xml", ""),
            label=_text(r, "label"),
            description=_text(r, "description"),
            process_type=_text(r, "processType"),
            status=_text(r, "status") or "Active",
            trigger_object=_text(start, "object") if start is not None else "",
            record_trigger_type=_text(start, "recordTriggerType") if start is not None else "",
            path=str(p),
        ))
    return out


def parse_apex(root: Path) -> list:
    out = []
    for p in root.rglob("*.cls"):
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"\b(with sharing|without sharing|inherited sharing)\b", body, re.I)
        out.append(ApexClassMeta(api_name=p.stem, body=body,
                                 sharing=m.group(1).lower() if m else "", path=str(p)))
    return out


def parse_triggers(root: Path) -> list:
    out = []
    for p in root.rglob("*.trigger"):
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"trigger\s+(\w+)\s+on\s+(\w+)\s*\(([^)]*)\)", body, re.I)
        out.append(ApexTriggerMeta(
            api_name=m.group(1) if m else p.stem,
            object_name=m.group(2) if m else "",
            events=[e.strip() for e in m.group(3).split(",")] if m else [],
            body=body, path=str(p),
        ))
    return out


def parse_permission_sets(root: Path) -> list:
    out = []
    for p in root.rglob("*.permissionset-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except ET.ParseError:
            continue
        perms = [_text(up, "name") for up in r.findall("sf:userPermissions", NS)
                 if _text(up, "enabled").lower() == "true"]
        objs = []
        for op in r.findall("sf:objectPermissions", NS):
            objs.append(ObjectPerm(
                object_name=_text(op, "object"),
                allow_edit=_text(op, "allowEdit").lower() == "true",
                allow_delete=_text(op, "allowDelete").lower() == "true",
                modify_all=_text(op, "modifyAllRecords").lower() == "true",
                view_all=_text(op, "viewAllRecords").lower() == "true",
            ))
        out.append(PermissionSetMeta(
            api_name=p.name.replace(".permissionset-meta.xml", ""),
            label=_text(r, "label"), user_permissions=perms, object_perms=objs, path=str(p),
        ))
    return out


def parse_project(root: Path) -> OrgMetadata:
    """Parse everything D3/D4/D5 need out of an SFDX directory."""
    return OrgMetadata(
        flows=parse_flows(root),
        apex=parse_apex(root),
        triggers=parse_triggers(root),
        permission_sets=parse_permission_sets(root),
        record_stats=[],          # source mode has no record data
    )


# ------------------------------------------------------- body heuristics

_DML = re.compile(r"\b(insert|update|delete|upsert)\s+\w|Database\.(insert|update|delete|upsert)", re.I)
_SOQL = re.compile(r"\[\s*SELECT\b", re.I)
_LOOP = re.compile(r"\b(for|while)\s*\(")


def _loop_blocks(body: str):
    """Yield the source of each loop body, by brace matching. Heuristic."""
    for m in _LOOP.finditer(body):
        i = body.find("{", m.end())
        if i == -1:
            continue
        depth, j = 0, i
        while j < len(body):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield body[i:j]


def dml_in_loop(body: str) -> int:
    return sum(1 for b in _loop_blocks(body) if _DML.search(b))


def soql_in_loop(body: str) -> int:
    return sum(1 for b in _loop_blocks(body) if _SOQL.search(b))


def has_recursion_guard(body: str) -> bool:
    """A static flag / processed-id set is the common guard idiom."""
    return bool(re.search(r"static\s+(Boolean|Set\s*<\s*Id\s*>)", body, re.I)
                or re.search(r"\b(hasRun|alreadyRun|isRunning|processedIds)\b", body, re.I))
