#!/usr/bin/env python3
"""
Metadata model + SFDX parsers for the dimensions beyond D1.

D1 needs only field metadata. D3/D4/D5 need Flows, Apex, triggers and permission
sets — this module turns those files into plain dataclasses, so the rule packs
operate on parsed structures rather than on file paths. The same structures can
be built in memory (by the portfolio generator), which means one set of rules
serves both a real SFDX project and the synthetic demo corpus.

Reports and dashboards are parsed too, but not as a dimension: they are a
blast-radius signal. A badly named field that forty reports depend on is a
different remediation decision from one nobody has touched in years.

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
class ReportRefs:
    """How often each field is consumed by a report or dashboard.

    report_count is every reporting document parsed — reports *and* dashboards,
    because a dashboard-only project still has real consumers, and `available`
    gates on this count. dashboard_count is the dashboard subset, so a caller
    that wants reports alone can subtract it.

    refs maps "Object.Field" -> number of documents referencing it. A field is
    counted once per document however many columns, filters and groupings use
    it. Bare "Field" keys are stored alongside the qualified ones: report XML
    does not always name the object, so lookups need something to fall back to.
    """
    report_count: int = 0
    refs: dict = dc_field(default_factory=dict)     # "Object.Field" | "Field" -> doc count
    dashboard_count: int = 0
    dashboard_reports: dict = dc_field(default_factory=dict)  # report api name -> dashboards
    # lowercased key -> the casing actually stored in refs. Report metadata mixes
    # "Account.Name" with the legacy "ACCOUNT.NAME" token for the same field.
    _lower: dict = dc_field(default_factory=dict, repr=False)

    def referenced(self, object_name: str, field_api: str) -> int:
        """Documents referencing this field. Case-insensitive, and tolerant of
        both stored forms: an exact Object.Field hit wins, otherwise fall back
        to the bare field name. The qualified hit is preferred because it is the
        precise answer — falling back would count same-named fields on other
        objects, and overstating blast radius is the expensive error here."""
        if len(self._lower) != len(self.refs):
            self._reindex()
        # tolerate a caller passing an already-qualified field
        fkey = _leaf(field_api).lower()
        if not fkey:
            return 0
        okey = _leaf(object_name).lower()
        if okey:
            hit = self.refs.get(self._lower.get(okey + "." + fkey, ""), 0)
            if hit:
                return hit
        return self.refs.get(self._lower.get(fkey, ""), 0)

    @property
    def available(self) -> bool:
        return self.report_count > 0

    def _reindex(self) -> None:
        self._lower = {k.lower(): k for k in self.refs}


@dataclass
class OrgMetadata:
    """Everything the D3/D4/D5 packs need. Empty lists mean 'not available',
    which is what drives the assessed/not-assessed decision."""
    flows: list = dc_field(default_factory=list)
    apex: list = dc_field(default_factory=list)
    triggers: list = dc_field(default_factory=list)
    permission_sets: list = dc_field(default_factory=list)
    record_stats: list = dc_field(default_factory=list)
    # Deliberately last: existing callers construct the five lists above.
    report_refs: ReportRefs = dc_field(default_factory=ReportRefs)

    def assessable_dims(self) -> set:
        """Which dimensions actually have inputs. D1 is decided by the caller
        (it needs fields, which the D1 scanner already parses). Report refs are
        deliberately absent: they weight existing findings, they do not score."""
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


# --------------------------------------------------- reports & dashboards

# Leaf tags whose text is a column reference. Collected by local name anywhere in
# the document rather than by fixed paths, because the same reference appears
# under columns, filters, groupings, charts, buckets and cross filters, and the
# shape differs between API versions.
_REF_TAGS = {
    "field",                    # <columns>, <groupingsDown>, <groupingsAcross>, <filters>
    "column",                   # <criteriaItems>, <chartSummaries>, <dashboardFilterColumns>
    "groupingColumn",           # chart and dashboard component groupings
    "sourceColumnName",         # bucket fields
    "dateColumn",               # <timeFrameFilter>
    "relatedTableJoinColumn",   # cross filters
}

# Report field tokens: "Account.Name", "ACCOUNT.NAME", "Account$Custom__c",
# "Opportunity.Account$Name" (relationship path — last hop is the field).
_FORMULA_REF = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:[.$][A-Za-z][A-Za-z0-9_]*)+")

# Enough of the standard objects to decode the common report type names.
# Longest first so "OpportunityLineItem" beats "Opportunity".
_STD_OBJECTS = sorted(
    ["Account", "Asset", "Campaign", "CampaignMember", "Case", "Contact", "Contract",
     "Event", "Lead", "Opportunity", "OpportunityLineItem", "Order", "Product2",
     "Pricebook2", "Quote", "Solution", "Task", "User"],
    key=len, reverse=True)


def _local(tag) -> str:
    # tag is a callable for comments/PIs, which is why this is not just rsplit
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _hops(ref: str) -> list:
    """Segments of a reference path. Reports separate them with '.' or '$'."""
    return [p for p in re.split(r"[.$]", (ref or "").strip()) if p]


def _leaf(ref: str) -> str:
    """Last hop of a reference path — the field itself."""
    parts = _hops(ref)
    return parts[-1] if parts else ""


def _split_ref(ref: str):
    """('Object', 'Field') for a report column token; object is '' when the
    token is bare. Relationship paths keep only their last hop."""
    parts = _hops(ref)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return parts[-2], parts[-1]


def _object_from_report_type(report_type: str) -> str:
    """Best-effort primary object from <reportType>. Standard types read
    'AccountList' / 'OpportunityHistory'; custom ones are a developer name that
    tells us nothing, so we give up rather than guess. Guessing wrong is cheap
    anyway — every reference is also stored bare, so lookups still resolve."""
    head = re.split(r"[$@]", (report_type or "").strip())[0]
    if not head:
        return ""
    base = re.sub(r"List$", "", head)
    low = base.lower()
    for obj in _STD_OBJECTS:
        if low == obj.lower() or low.startswith(obj.lower()):
            return obj
    return base if base.endswith("__c") else ""


def _doc_refs(root) -> set:
    """Canonical keys for one report or dashboard, deduplicated: a field used in
    a column, a filter and a grouping is still one document referencing it."""
    tokens = []
    report_type = ""
    for el in root.iter():
        if not el.text:
            continue
        name = _local(el.tag)
        if name in _REF_TAGS:
            tokens.append(el.text.strip())
        elif name == "calculatedFormula":       # custom summary formulas cite columns
            tokens.extend(_FORMULA_REF.findall(el.text))
        elif name == "reportType" and not report_type:
            report_type = el.text.strip()

    pairs = [_split_ref(t) for t in tokens]
    pairs = [(o, f) for o, f in pairs if f]

    # The report's own qualifiers are a better primary-object signal than
    # <reportType>: the majority of columns name the object the report is built on.
    counts = {}
    for obj, _ in pairs:
        if obj:
            counts[obj] = counts.get(obj, 0) + 1
    if counts:
        primary = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    else:
        primary = _object_from_report_type(report_type)

    keys = set()
    for obj, fld in pairs:
        keys.add(fld)                       # bare form: the fallback for lookups
        owner = obj or primary
        if owner:
            keys.add(owner + "." + fld)
    return keys


def _absorb(out: ReportRefs, keys) -> None:
    """Count one document's keys, keeping the first casing seen for each key so
    'ACCOUNT.NAME' and 'Account.Name' do not become two separate tallies."""
    for key in sorted(keys):
        canon = out._lower.setdefault(key.lower(), key)
        out.refs[canon] = out.refs.get(canon, 0) + 1


def parse_reports(root: Path) -> ReportRefs:
    """Field references from *.report-meta.xml and *.dashboard-meta.xml.

    Malformed XML is skipped, not fatal — an org's reports folder is the least
    curated metadata in it. Paths are walked in sorted order so two runs over
    the same tree produce identical keys."""
    out = ReportRefs()

    for p in sorted(root.rglob("*.report-meta.xml")):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
            continue
        out.report_count += 1
        _absorb(out, _doc_refs(r))

    for p in sorted(root.rglob("*.dashboard-meta.xml")):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
            continue
        out.report_count += 1
        out.dashboard_count += 1
        _absorb(out, _doc_refs(r))
        # <components><report>Folder/Report_Name</report> — keep the developer
        # name, which is what the .report-meta.xml file is called.
        for el in r.iter():
            if _local(el.tag) == "report" and el.text:
                name = el.text.strip().rsplit("/", 1)[-1]
                if name:
                    out.dashboard_reports[name] = out.dashboard_reports.get(name, 0) + 1

    return out


def parse_project(root: Path) -> OrgMetadata:
    """Parse everything D3/D4/D5 need out of an SFDX directory."""
    return OrgMetadata(
        flows=parse_flows(root),
        apex=parse_apex(root),
        triggers=parse_triggers(root),
        permission_sets=parse_permission_sets(root),
        record_stats=[],          # source mode has no record data
        report_refs=parse_reports(root),
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
