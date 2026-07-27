#!/usr/bin/env python3
"""
Org mode — collect the same structures scanner/metadata.py parses out of a
directory, but from a live org, over the `sf` CLI.

Until this existed, `--mode Org` was a label written onto a scan record: every
byte of evidence still came from files on disk. This module is the org half.
It returns `metadata.OrgMetadata`, populated with the identical dataclasses the
SFDX parsers produce, so every rule pack in scanner/rules_ext.py runs unchanged
on org-collected input — there is no org-specific rule and no second code path
through scoring.

WHAT IT COLLECTS
  usage.report_references   Report/Dashboard inventory via SOQL, field-level
                            references via the Analytics REST describe endpoint.
  permissions.permission_sets  PermissionSet + ObjectPermissions (D4). Managed
                            sets are excluded by default and flows are not —
                            see collect_permission_sets for the reasoning.
  automation.flows          FlowDefinitionView (D3, and the flow half of D5).
  automation.apex_classes   ApexClass incl. Body, Tooling API (D3/D5).
  automation.triggers_flows ApexTrigger incl. Body, plus record-triggered flows.
  data.record_stats         Bounded COUNT() probes per object (D2) — the first
                            time D2 can run on anything real.
  metadata.field_schema     FieldDefinition + describe, so D1 works in org mode.

DEGRADATION IS THE POINT
Every collector is independent and every one of them can fail on its own. A
query that is rejected, an object that is not queryable, an endpoint the
running user has no licence for: each records its signal as UNAVAILABLE with
the reason, and collection continues. A partial collection is the normal case,
not an error case, and it is reported rather than papered over. Two rules this
module will not break:

  * A signal that was not collected reduces coverage. It never defaults to a
    benign value that is then read as a measurement. `ReportRefs.report_count`
    counts only documents whose field references were actually read, never the
    inventory — because that count gates D1.UNREFERENCED_FIELD, and a scan that
    could not open a single report must not go on to declare every field in the
    org unused.
  * Apex whose Body comes back as "(hidden)" (managed package code) is dropped,
    not analysed. An empty-looking body scores clean on every D5 heuristic, and
    "we could not read it" is not "it is fine".

API COST
Reads only; this module never writes to the org. Costs are per invocation of
`sf`, each of which is at least one API call (more when a result paginates):

  flows              1
  apex classes       1 (+1 count)
  triggers           1
  permission sets    1 + ceil(user-permission columns / 150) + 1 for ObjectPermissions
  report references  2 (inventory) + 1 per document described, capped by --doc-limit
  field schema       2 per object (FieldDefinition query + describe)
  record stats       up to 3 + N per object, N = --fill-sample fields (default 6):
                     one COUNT() for the total, one per sampled field for the
                     fill rate, one for staleness, one GROUP BY for duplicates

The record-stat probes are deliberately all COUNT()/aggregate queries — no
`SELECT *` over a large object, nothing that streams rows. The duplicate probe
is the one query that scans every row of the object, so it is skipped above
`--dup-ceiling` records (default 200k) and says so rather than running an
unbounded aggregate against a production org.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field as dc_field

import metadata as md

DEFAULT_TIMEOUT = 300          # seconds per sf invocation
FILL_SAMPLE_FIELDS = 6         # fields averaged for a fill rate
DUP_SCAN_CEILING = 200_000     # above this, skip the duplicate aggregate
DUP_GROUP_LIMIT = 500          # rows returned by the duplicate aggregate
DOC_DESCRIBE_LIMIT = 50        # reports/dashboards described per scan
STALE_MONTHS = 24              # matches the D2.STALE_DATA wording
PERM_COLUMN_CHUNK = 150        # Permissions* columns per SOQL query

# System fields that carry no business meaning, so no fill rate is worth
# spending an API call on.
_SYSTEM_FIELDS = {
    "Id", "IsDeleted", "CreatedDate", "CreatedById", "LastModifiedDate",
    "LastModifiedById", "SystemModstamp", "LastActivityDate", "LastViewedDate",
    "LastReferencedDate", "OwnerId", "RecordTypeId", "MayEdit", "IsLocked",
    "UserRecordAccessId", "RecordVisibilityId",
}


class SfError(RuntimeError):
    """A `sf` invocation failed. The message is already redacted."""


# ------------------------------------------------------------ plumbing

# Anything shaped like a session id or a bearer token, so a CLI error that
# echoes a request never reaches a note, a log line or a scan record.
_SECRET = re.compile(
    r"(00[A-Za-z0-9]{13,15}![A-Za-z0-9._\-]+)"          # session id
    r"|((?i:bearer)\s+[A-Za-z0-9._\-]{20,})"            # Authorization header
    r"|((?i:(access|refresh)_?token)[\"'\s:=]+[A-Za-z0-9._\-!]{10,})"
)


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text or "")


@dataclass
class Note:
    """One line of the collection log.

    `signal` is a metadata.SIGNAL_* name and marks the collector's *verdict* on
    that signal — exactly one note per signal carries it. Sub-failures inside a
    collector (one permission-column chunk, one object's help text) carry ""
    instead: they are real losses worth logging, but they do not by themselves
    decide whether the signal was collected. Letting them decide would knock D4
    out entirely because one of six column chunks timed out."""
    signal: str
    state: str            # md.COLLECTED | md.UNAVAILABLE
    detail: str
    subject: str = ""     # object / component the note is about

    def line(self) -> str:
        mark = "ok  " if self.state == md.COLLECTED else "MISS"
        who = (self.signal or "-") + ((" [" + self.subject + "]") if self.subject else "")
        return mark + " " + who + ": " + self.detail


@dataclass
class OrgCollection:
    """What one org-mode run produced: the metadata the rules consume, plus an
    honest account of what was and was not obtained."""
    org: str
    org_id: str = ""
    org_name: str = ""
    metadata: md.OrgMetadata = dc_field(default_factory=md.OrgMetadata)
    # orgiq_spike.Field records. Kept beside OrgMetadata rather than inside it
    # because that is where source mode keeps them too — the D1 scanner owns
    # Field, and metadata.py must not import the scanner it is imported by.
    fields: list = dc_field(default_factory=list)
    notes: list = dc_field(default_factory=list)
    cli_invocations: int = 0

    def missing(self) -> list:
        return sorted(self.metadata.missing_signals())

    def summary(self) -> str:
        m = self.metadata
        lines = ["Org collection: " + (self.org_name or self.org)
                 + ((" (" + self.org_id + ")") if self.org_id else "")]
        lines.append("  sf invocations: " + str(self.cli_invocations))
        lines.append("  collected: flows=" + str(len(m.flows))
                     + " apex=" + str(len(m.apex))
                     + " triggers=" + str(len(m.triggers))
                     + " permission_sets=" + str(len(m.permission_sets))
                     + " record_stats=" + str(len(m.record_stats))
                     + " report_docs_read=" + str(m.report_refs.report_count)
                     + " fields=" + str(m.field_count))
        lines.append("  signals present: "
                     + (", ".join(sorted(m.present_signals())) or "(none)"))
        lines.append("  signals missing: " + (", ".join(self.missing()) or "(none)"))
        lines.append("  coverage:")
        for _, cov in sorted(m.coverage().items()):
            lines.append("    " + cov.explain())
        lines.append("  log:")
        for n in self.notes:
            lines.append("    " + n.line())
        return "\n".join(lines)


class _Client:
    """Thin wrapper over the `sf` CLI. Holds the note log and the call count so
    every collector degrades the same way."""

    def __init__(self, org: str, timeout: int = DEFAULT_TIMEOUT, verbose: bool = False):
        self.org = org
        self.timeout = timeout
        self.verbose = verbose
        self.notes = []
        self.calls = 0
        # Field collection and the D2 probes both need an object's describe.
        # Cached because it is the same answer and an API call is an API call.
        self._describes = {}
        if not shutil.which("sf"):
            raise SfError("the Salesforce CLI (`sf`) is not on PATH")

    # -- logging

    def ok(self, signal: str, detail: str, subject: str = "") -> None:
        self.notes.append(Note(signal, md.COLLECTED, detail, subject))

    def miss(self, signal: str, detail: str, subject: str = "") -> None:
        self.notes.append(Note(signal, md.UNAVAILABLE, _redact(detail), subject))

    def gap(self, detail: str, subject: str = "") -> None:
        """A loss inside a collector that does not on its own decide the signal."""
        self.notes.append(Note("", md.UNAVAILABLE, _redact(detail), subject))

    # -- invocation

    def _run(self, args: list) -> dict:
        self.calls += 1
        if self.verbose:
            print("$ sf " + " ".join(args), file=sys.stderr)
        try:
            proc = subprocess.run(["sf"] + args + ["--json"],
                                  capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise SfError("sf timed out after " + str(self.timeout) + "s")
        except OSError as exc:
            raise SfError("could not run sf: " + _redact(str(exc)))

        raw = proc.stdout.strip()
        if not raw:
            raise SfError("sf produced no output (exit " + str(proc.returncode) + "): "
                          + _redact(proc.stderr.strip())[:200])
        try:
            payload = json.loads(raw)
        except ValueError:
            raise SfError("sf produced non-JSON output: " + _redact(raw)[:200])

        if isinstance(payload, dict) and payload.get("status", 0) != 0:
            code = payload.get("data", {}).get("errorCode") or payload.get("name") or "error"
            msg = (payload.get("message") or "").splitlines()
            first = next((s.strip() for s in msg if s.strip()), "")
            raise SfError(_redact(str(code) + ": " + first)[:300])
        return payload

    # -- typed calls

    def query(self, soql: str, tooling: bool = False) -> dict:
        """Returns the raw result block: {records, totalSize, done}. COUNT()
        queries carry their answer in totalSize with no records, which is why
        this hands back the block rather than just the rows."""
        args = ["data", "query", "-o", self.org, "-q", soql]
        if tooling:
            args.append("--use-tooling-api")
        return self._run(args).get("result") or {}

    def rows(self, soql: str, tooling: bool = False) -> list:
        return self.query(soql, tooling).get("records") or []

    def count(self, soql: str, tooling: bool = False) -> int:
        return int(self.query(soql, tooling).get("totalSize") or 0)

    def describe(self, sobject: str) -> dict:
        if sobject in self._describes:
            cached = self._describes[sobject]
            if isinstance(cached, SfError):
                raise cached
            return cached
        try:
            out = self._run(["sobject", "describe", "-o", self.org,
                             "-s", sobject]).get("result") or {}
        except SfError as exc:
            # Cache the failure too, or a broken object costs one call per caller.
            self._describes[sobject] = exc
            raise
        self._describes[sobject] = out
        return out

    def rest(self, path: str):
        """A raw REST GET. Used for the Analytics describe endpoints, which have
        no SOQL equivalent. `sf api request rest` prints the body directly, and
        prints a JSON error array when the call is refused."""
        self.calls += 1
        if self.verbose:
            print("$ sf api request rest " + path, file=sys.stderr)
        try:
            proc = subprocess.run(["sf", "api", "request", "rest", path, "-o", self.org],
                                  capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise SfError("sf timed out after " + str(self.timeout) + "s")
        except OSError as exc:
            raise SfError("could not run sf: " + _redact(str(exc)))
        raw = proc.stdout.strip()
        # The command is flagged beta and prints a warning on stdout's first
        # line in some versions; take the JSON body only.
        cut = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0] or [0])
        try:
            body = json.loads(raw[cut:])
        except ValueError:
            raise SfError("REST call returned non-JSON: " + _redact(raw)[:200])
        if isinstance(body, list) and body and isinstance(body[0], dict) and "errorCode" in body[0]:
            raise SfError(_redact(str(body[0].get("errorCode")) + ": "
                                  + str(body[0].get("message", "")))[:300])
        return body


def _api_name(record: dict, name_key: str = "ApiName") -> str:
    """Namespaced api name, so a finding about a managed component says so in
    its own component name instead of looking like the customer's work."""
    ns = record.get("NamespacePrefix")
    base = record.get(name_key) or ""
    return (ns + "__" + base) if ns else base


def _q(value: str) -> str:
    """Escape a literal for a SOQL string. Only used on api names we read back
    out of the org, but a name with a quote in it should not build a broken
    query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


# ------------------------------------------------------------ collectors
#
# Each collector takes the client and returns its part of OrgMetadata, calling
# client.ok()/client.miss() exactly once for the signal it owns. None of them
# raise: a failure here is a reported gap, not a crashed scan.

def collect_flows(client: _Client, include_managed: bool = True) -> list:
    """FlowDefinitionView — one query for every flow the org can see.

    Managed-package flows are included by default, and that is a deliberate
    difference from source mode. Source mode sees the files in your repo; the
    question org mode answers is what an agent could actually invoke in this
    org, and a packaged autolaunched flow is invocable. They are namespaced in
    the api name so no finding blames the customer for a vendor's flow."""
    where = "" if include_managed else " WHERE NamespacePrefix = null"
    soql = ("SELECT ApiName, Label, NamespacePrefix, ProcessType, TriggerType, "
            "IsActive, Description, TriggerObjectOrEvent.QualifiedApiName "
            "FROM FlowDefinitionView" + where)
    try:
        rows = client.rows(soql)
    except SfError as exc:
        client.miss(md.SIGNAL_FLOWS, "FlowDefinitionView query failed — " + str(exc))
        return []

    out = []
    for r in rows:
        trig = r.get("TriggerObjectOrEvent") or {}
        trigger_type = r.get("TriggerType") or ""
        # FlowDefinitionView reports activation, not the three-state Status the
        # metadata file carries. Draft is the honest label for "not active":
        # Obsolete is indistinguishable from here, and the D3 rule only cares
        # that a non-Active flow cannot be invoked.
        out.append(md.FlowMeta(
            api_name=_api_name(r),
            label=r.get("Label") or "",
            description=r.get("Description") or "",
            process_type=r.get("ProcessType") or "",
            status="Active" if r.get("IsActive") else "Draft",
            trigger_object=(trig.get("QualifiedApiName") or "")
            if trigger_type in ("RecordBeforeSave", "RecordAfterSave", "RecordBeforeDelete")
            else "",
            record_trigger_type=trigger_type,
            path="FlowDefinitionView/" + _api_name(r),
        ))
    managed = sum(1 for r in rows if r.get("NamespacePrefix"))
    client.ok(md.SIGNAL_FLOWS,
              str(len(out)) + " flow(s); " + str(managed) + " from managed packages"
              + ("" if include_managed else " (excluded)"))
    return out


def collect_apex(client: _Client, include_managed: bool = True) -> list:
    """ApexClass with bodies, via the Tooling API.

    A managed class returns the literal string "(hidden)" for Body. Those are
    dropped rather than parsed: every D5 body heuristic scores "(hidden)" as
    clean, and reporting a class we could not read as clean is the exact
    overclaim this project exists to avoid.

    If classes exist and NONE of them could be read, the signal is unavailable,
    not empty. The difference decides whether D3.NO_SAFE_ACTIONS is allowed to
    fire: "the org has no Apex" supports the claim that nothing is invocable,
    "the org has four classes we were not permitted to open" does not — an
    @InvocableMethod could be sitting in any of them."""
    where = "" if include_managed else " WHERE NamespacePrefix = null"
    soql = ("SELECT Name, NamespacePrefix, Body, ApiVersion, Status "
            "FROM ApexClass" + where)
    try:
        rows = client.rows(soql, tooling=True)
    except SfError as exc:
        client.miss(md.SIGNAL_APEX, "ApexClass query failed — " + str(exc))
        return []

    out, hidden = [], 0
    for r in rows:
        body = r.get("Body") or ""
        if body.strip() == "(hidden)":
            hidden += 1
            continue
        m = re.search(r"\b(with sharing|without sharing|inherited sharing)\b", body, re.I)
        out.append(md.ApexClassMeta(
            api_name=_api_name(r, "Name"),
            body=body,
            sharing=m.group(1).lower() if m else "",
            path="ApexClass/" + _api_name(r, "Name"),
        ))
    detail = str(len(out)) + " class body/bodies read"
    if hidden:
        detail += "; " + str(hidden) + " managed class(es) returned (hidden) and were dropped"
    if hidden and not out:
        client.miss(md.SIGNAL_APEX,
                    "all " + str(hidden) + " Apex class(es) in this org returned a hidden "
                    "body (managed package code); no Apex was analysable, so D3 must not "
                    "conclude anything about what this org's Apex does or does not expose")
        return out
    client.ok(md.SIGNAL_APEX, detail)
    return out


def collect_triggers(client: _Client, include_managed: bool = True) -> list:
    """ApexTrigger with bodies. Same (hidden) rule as Apex classes.

    TableEnumOrId is the object name for a standard object and an 18-char id for
    a custom one, so custom-object triggers get their object resolved from the
    body's `trigger X on Y` clause — the same regex source mode uses."""
    where = "" if include_managed else " WHERE NamespacePrefix = null"
    soql = ("SELECT Name, NamespacePrefix, TableEnumOrId, Body, Status, "
            "UsageBeforeInsert, UsageAfterInsert, UsageBeforeUpdate, "
            "UsageAfterUpdate, UsageBeforeDelete, UsageAfterDelete, "
            "UsageAfterUndelete FROM ApexTrigger" + where)
    try:
        rows = client.rows(soql, tooling=True)
    except SfError as exc:
        client.miss(md.SIGNAL_TRIGGERS_FLOWS, "ApexTrigger query failed — " + str(exc))
        return []

    events = [("UsageBeforeInsert", "before insert"), ("UsageAfterInsert", "after insert"),
              ("UsageBeforeUpdate", "before update"), ("UsageAfterUpdate", "after update"),
              ("UsageBeforeDelete", "before delete"), ("UsageAfterDelete", "after delete"),
              ("UsageAfterUndelete", "after undelete")]
    out, hidden = [], 0
    for r in rows:
        body = r.get("Body") or ""
        if body.strip() == "(hidden)":
            hidden += 1
            continue
        obj = r.get("TableEnumOrId") or ""
        if re.fullmatch(r"[a-zA-Z0-9]{15,18}", obj):
            m = re.search(r"trigger\s+\w+\s+on\s+(\w+)", body, re.I)
            obj = m.group(1) if m else obj
        out.append(md.ApexTriggerMeta(
            api_name=_api_name(r, "Name"),
            object_name=obj,
            events=[label for key, label in events if r.get(key)],
            body=body,
            path="ApexTrigger/" + _api_name(r, "Name"),
        ))
    detail = str(len(out)) + " trigger(s) read"
    if hidden:
        detail += "; " + str(hidden) + " managed trigger(s) returned (hidden) and were dropped"
    if hidden and not out:
        # Same reasoning as Apex: an unreadable trigger is not an absent one,
        # and D5.MULTIPLE_TRIGGERS counting to zero would be a lie.
        client.miss(md.SIGNAL_TRIGGERS_FLOWS,
                    "all " + str(hidden) + " trigger(s) returned a hidden body "
                    "(managed package code); the automation graph could not be built "
                    "from the trigger side")
        return out
    # collect() revisits this note once the flows are known, because D5 also
    # runs off record-triggered flows.
    client.ok(md.SIGNAL_TRIGGERS_FLOWS, detail)
    return out


def collect_permission_sets(client: _Client, include_managed: bool = False) -> list:
    """PermissionSet + ObjectPermissions.

    Two exclusions, both of which change what D4 reports, so both are stated
    here and counted in the note rather than applied silently.

    Profile-owned permission sets are always excluded. They are the shadow
    records behind every Profile in the org — 44 of them in a stock Developer
    Edition, named things like `X00e1a000000MWaPAAW` — and source mode never
    sees them, because a Profile is not a `*.permissionset-meta.xml`.

    Managed-package permission sets are excluded by DEFAULT, unlike flows and
    Apex. The asymmetry is deliberate. D3 asks what an agent can invoke, and a
    packaged flow is just as invocable as yours. D4 asks what to narrow, and a
    packaged permission set is not yours to narrow: in this Developer Edition a
    single vendor set grants Modify All Records on 90-odd standard objects and
    would bury the org's own D4 findings under vendor grants no admin can edit.
    Pass include_managed=True to see them; the count is reported either way.

    The user-permission columns are read from the sobject describe and queried
    in chunks: PermissionSet carries roughly 570 `Permissions*` booleans, more
    than one SOQL statement should ask for at once."""
    try:
        desc = client.describe("PermissionSet")
    except SfError as exc:
        client.miss(md.SIGNAL_PERMISSION_SETS, "PermissionSet describe failed — " + str(exc))
        return []
    perm_cols = sorted(f["name"] for f in desc.get("fields", [])
                       if str(f.get("name", "")).startswith("Permissions"))

    where = "IsOwnedByProfile = false"
    if not include_managed:
        where += " AND NamespacePrefix = null"

    try:
        base = client.rows("SELECT Id, Name, Label, NamespacePrefix, Type "
                           "FROM PermissionSet WHERE IsOwnedByProfile = false")
    except SfError as exc:
        client.miss(md.SIGNAL_PERMISSION_SETS, "PermissionSet query failed — " + str(exc))
        return []

    managed_total = sum(1 for r in base if r.get("NamespacePrefix"))
    if not include_managed:
        base = [r for r in base if not r.get("NamespacePrefix")]

    by_id = {}
    for r in base:
        by_id[r["Id"]] = md.PermissionSetMeta(
            api_name=_api_name(r, "Name"),
            label=r.get("Label") or "",
            path="PermissionSet/" + str(r.get("Id")),
        )

    # User permissions, chunked. A failed chunk costs only the perms in it, so
    # it is recorded and the rest still land.
    chunks = int(math.ceil(len(perm_cols) / float(PERM_COLUMN_CHUNK))) if perm_cols else 0
    lost = 0
    for i in range(chunks):
        cols = perm_cols[i * PERM_COLUMN_CHUNK:(i + 1) * PERM_COLUMN_CHUNK]
        soql = "SELECT Id," + ",".join(cols) + " FROM PermissionSet WHERE " + where
        try:
            for r in client.rows(soql):
                ps = by_id.get(r.get("Id"))
                if ps is None:
                    continue
                for col in cols:
                    if r.get(col):
                        # Strip the SOQL prefix: rules ask for "ModifyAllData",
                        # which is what the metadata file calls it.
                        ps.user_permissions.append(col[len("Permissions"):])
        except SfError as exc:
            lost += len(cols)
            client.gap("user-permission columns " + str(i * PERM_COLUMN_CHUNK) + "-"
                       + str(i * PERM_COLUMN_CHUNK + len(cols)) + " unavailable — " + str(exc))

    # Object permissions.
    obj_where = "Parent.IsOwnedByProfile = false"
    if not include_managed:
        obj_where += " AND Parent.NamespacePrefix = null"
    obj_ok = True
    try:
        for r in client.rows(
                "SELECT ParentId, SobjectType, PermissionsEdit, PermissionsDelete, "
                "PermissionsModifyAllRecords, PermissionsViewAllRecords "
                "FROM ObjectPermissions WHERE " + obj_where):
            ps = by_id.get(r.get("ParentId"))
            if ps is None:
                continue
            ps.object_perms.append(md.ObjectPerm(
                object_name=r.get("SobjectType") or "",
                allow_edit=bool(r.get("PermissionsEdit")),
                allow_delete=bool(r.get("PermissionsDelete")),
                modify_all=bool(r.get("PermissionsModifyAllRecords")),
                view_all=bool(r.get("PermissionsViewAllRecords")),
            ))
    except SfError as exc:
        obj_ok = False
        client.gap("ObjectPermissions query failed — " + str(exc))

    out = sorted(by_id.values(), key=lambda p: p.api_name)
    detail = (str(len(out)) + " permission set(s); profile-owned excluded; "
              + ("managed included" if include_managed
                 else "managed-package sets excluded (" + str(managed_total) + " skipped)")
              + "; " + str(len(perm_cols) - lost) + "/" + str(len(perm_cols))
              + " user-permission columns read")
    if not obj_ok:
        # The rules read object_perms directly, so losing them is not a partial
        # answer for D4 — three of its four rules go blind.
        client.miss(md.SIGNAL_PERMISSION_SETS,
                    detail + "; ObjectPermissions UNAVAILABLE, so object-level grants "
                    "could not be assessed at all")
        return out
    client.ok(md.SIGNAL_PERMISSION_SETS, detail)
    return out


# ---------------------------------------------------- reports & dashboards

# Keys whose value is a column token, or a list of them. The REST shape is
# nested JSON rather than the XML source mode parses, but the tokens are the
# same strings — "Account.Name", "Opportunity$Amount" — so they go through
# metadata._split_ref and land in the same key space.
_COLUMN_KEYS = {
    "detailColumns",            # list[str]
    "aggregates",               # list[str] — summary columns
    "column",                   # reportFilters[], crossFilters[]
    "sourceColumnName",         # buckets[]
    "dateColumn",               # standardDateFilter
    "relatedTableJoinColumn",   # crossFilters[]
    "primaryTableColumn",       # crossFilters[]
    "groupingColumn",           # chart / dashboard component groupings
}
# Keys holding a list of grouping objects, each naming its column under "name".
# "name" is only read here: at the top level of a describe payload it is the
# report's own title, and hoovering that up would file the report name as a
# field reference.
_GROUPING_KEYS = {"groupingsDown", "groupingsAcross", "groupings"}


def _walk_report_refs(node, out: set) -> None:
    """Pull column tokens out of an Analytics describe payload.

    Walked by key name rather than by fixed paths, for the same reason the XML
    parser is: detail columns, groupings, filters, aggregates, buckets and
    cross filters each name their column differently, and the shape moves
    between API versions."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in _COLUMN_KEYS:
                if isinstance(val, str):
                    out.add(val)
                elif isinstance(val, list):
                    out.update(v for v in val if isinstance(v, str))
                continue
            if key in _GROUPING_KEYS and isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        out.add(item["name"])
                continue
            _walk_report_refs(val, out)
    elif isinstance(node, list):
        for item in node:
            _walk_report_refs(item, out)


def _canonical_keys(tokens) -> set:
    """Same key space parse_reports builds: bare field plus Object.Field, with
    the report's dominant object standing in when a token is unqualified."""
    pairs = [md._split_ref(t) for t in tokens]
    pairs = [(o, f) for o, f in pairs if f]
    counts = {}
    for obj, _ in pairs:
        if obj:
            counts[obj] = counts.get(obj, 0) + 1
    primary = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if counts else ""
    keys = set()
    for obj, fld in pairs:
        keys.add(fld)
        owner = obj or primary
        if owner:
            keys.add(owner + "." + fld)
    return keys


def collect_report_refs(client: _Client, doc_limit: int = DOC_DESCRIBE_LIMIT,
                        api_version: str = "62.0") -> md.ReportRefs:
    """Report and dashboard field references.

    Two steps, because they fail independently. The SOQL inventory tells us how
    many reporting documents exist and is available to anyone who can see the
    folder. The field-level references need the Analytics REST describe
    endpoint, which requires privileges the running user may simply not have.

    `report_count` counts documents whose references were READ, never the
    inventory. That invariant is load-bearing: `ReportRefs.available` gates
    D1.UNREFERENCED_FIELD, and if the inventory alone set the count, a scan that
    was refused every describe call would go on to report every field in the org
    as referenced by nothing. The inventory is reported in the note instead."""
    out = md.ReportRefs()

    try:
        reports = client.rows("SELECT Id, Name, DeveloperName, FolderName FROM Report")
    except SfError as exc:
        client.gap("Report inventory query failed — " + str(exc))
        reports = []
    try:
        dashboards = client.rows("SELECT Id, Title, DeveloperName, FolderName FROM Dashboard")
    except SfError as exc:
        client.gap("Dashboard inventory query failed — " + str(exc))
        dashboards = []

    if not reports and not dashboards:
        client.miss(md.SIGNAL_REPORT_REFERENCES,
                    "no Report or Dashboard records are visible to this user")
        return out

    base = "/services/data/v" + api_version + "/analytics/"
    report_name = {r["Id"]: r.get("DeveloperName") or r.get("Name") or r["Id"]
                   for r in reports}

    read, refused = 0, []
    for r in reports[:doc_limit]:
        try:
            body = client.rest(base + "reports/" + r["Id"] + "/describe")
        except SfError as exc:
            refused.append(str(exc))
            continue
        tokens = set()
        inner = body.get("reportMetadata") if isinstance(body, dict) else None
        _walk_report_refs(inner if inner is not None else body, tokens)
        keys = _canonical_keys(tokens)
        if not keys:
            refused.append("described but yielded no column reference: "
                           + str(r.get("DeveloperName") or r["Id"]))
            continue
        md._absorb(out, keys)
        out.report_count += 1
        read += 1

    dash_read = 0
    for d in dashboards[:doc_limit]:
        try:
            body = client.rest(base + "dashboards/" + d["Id"] + "/describe")
        except SfError as exc:
            refused.append(str(exc))
            continue
        tokens = set()
        _walk_report_refs(body, tokens)
        keys = _canonical_keys(tokens)
        # The dashboard -> report edge is real even when no column reference is:
        # components name the report they render.
        for comp in (body.get("components") or []) if isinstance(body, dict) else []:
            rid = comp.get("reportId")
            if rid:
                name = report_name.get(rid, rid)
                out.dashboard_reports[name] = out.dashboard_reports.get(name, 0) + 1
        # Only count the dashboard as a read document if it actually yielded
        # column references — otherwise it inflates the denominator that
        # D1.UNREFERENCED_FIELD quotes.
        if keys:
            md._absorb(out, keys)
            out.report_count += 1
            out.dashboard_count += 1
            dash_read += 1

    inventory = str(len(reports)) + " report(s), " + str(len(dashboards)) + " dashboard(s)"
    if out.report_count == 0:
        why = ("describe refused for every document — " + refused[0]) if refused \
            else "no document yielded a field reference"
        client.miss(md.SIGNAL_REPORT_REFERENCES,
                    "inventory found " + inventory + " but no field references could be read ("
                    + why + "); D1.UNREFERENCED_FIELD stays disabled rather than "
                    "declaring fields unused on evidence we never obtained")
        return out

    detail = ("inventory " + inventory + "; field references read from "
              + str(read) + " report(s) and " + str(dash_read) + " dashboard(s), "
              + str(len(out.refs)) + " distinct field key(s)")
    if refused:
        detail += "; " + str(len(refused)) + " document(s) refused"
    if len(reports) > doc_limit or len(dashboards) > doc_limit:
        detail += "; capped at " + str(doc_limit) + " document(s) per type"
    client.ok(md.SIGNAL_REPORT_REFERENCES, detail)
    return out


# ---------------------------------------------------------- field schema

def collect_field_schema(client: _Client, objects) -> list:
    """Field metadata for D1, as `orgiq_spike.Field` records.

    Two calls per object: FieldDefinition carries the description (the single
    most important input D1 has) and the sobject describe carries inline help
    text, which FieldDefinition does not expose. Field ordering is sorted so two
    runs over an unchanged org produce identical output.

    Custom fields only, which is what keeps org mode and source mode saying the
    same thing about the same org. Source mode sees exactly the fields that have
    a `*.field-meta.xml`, and a custom object's stock `Name`, `CreatedDate` and
    `OwnerId` do not have one. Without this filter org mode opens every scan
    with D1.MISSING_DESCRIPTION on `Name` — true, since Name has no description,
    and useless, since it is not the customer's field to describe. The narrowing
    also loses descriptions on customised standard fields; that is the trade,
    and it is the conservative direction.

    Imported late and defensively: Field lives in the D1 scanner, and org mode
    is usable without it — a caller that only wants D2-D5 never triggers the
    import."""
    try:
        from orgiq_spike import Field
    except ImportError as exc:
        client.miss(md.SIGNAL_FIELD_SCHEMA,
                    "orgiq_spike.Field is not importable — " + str(exc))
        return []

    out, failed = [], []
    for obj in objects:
        try:
            rows = client.rows(
                "SELECT QualifiedApiName, Label, DataType, Description, IsCalculated "
                "FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = '"
                + _q(obj) + "'", tooling=True)
        except SfError as exc:
            failed.append(obj + " (" + str(exc) + ")")
            continue
        help_text = {}
        try:
            for f in client.describe(obj).get("fields", []):
                help_text[f.get("name")] = f.get("inlineHelpText") or ""
        except SfError:
            # Non-fatal: descriptions are what D1 reads, help text only softens
            # D1.MISSING_DESCRIPTION. Recorded per-object rather than as a
            # whole-signal failure.
            client.gap("inline help text unavailable", obj)
        for r in sorted(rows, key=lambda x: x.get("QualifiedApiName") or ""):
            api = r.get("QualifiedApiName") or ""
            if not api.endswith("__c") or api in _SYSTEM_FIELDS:
                continue
            out.append(Field(
                object_name=obj,
                api_name=api,
                label=r.get("Label") or "",
                type=r.get("DataType") or "",
                description=r.get("Description") or "",
                help_text=help_text.get(api, ""),
                path="FieldDefinition/" + obj + "." + api,
            ))

    if failed and not out:
        client.miss(md.SIGNAL_FIELD_SCHEMA,
                    "FieldDefinition unavailable for every object — " + failed[0])
        return []
    if not out:
        client.miss(md.SIGNAL_FIELD_SCHEMA,
                    "no custom field found on " + str(len(objects))
                    + " object(s); D1 has nothing to assess")
        return []
    detail = str(len(out)) + " custom field(s) across " + str(len(objects)) + " object(s)"
    if failed:
        detail += "; " + str(len(failed)) + " object(s) failed: " + ", ".join(failed[:3])
    client.ok(md.SIGNAL_FIELD_SCHEMA, detail)
    return out


# ---------------------------------------------------------- record stats

def _fill_candidates(desc: dict, limit: int) -> list:
    """Which fields a fill rate should average over.

    Bounded because each one costs an API call, deterministic because a scan
    that samples different fields on each run cannot be compared against its own
    history. Custom fields come first — they are where an org's own meaning
    lives, and the standard fields are populated by Salesforce anyway. Formula
    and non-filterable fields are excluded: a formula is never null in a way
    that means anything, and a non-filterable field cannot appear in the WHERE
    clause at all."""
    custom, standard = [], []
    for f in desc.get("fields", []):
        name = f.get("name") or ""
        if (name in _SYSTEM_FIELDS or not f.get("filterable") or not f.get("nillable")
                or f.get("calculated") or f.get("autoNumber")
                or f.get("type") in ("reference", "base64", "address", "location")):
            continue
        (custom if f.get("custom") else standard).append(name)
    return (sorted(custom) + sorted(standard))[:limit]


def _dup_key(desc: dict) -> str:
    """The field a duplicate probe may group on.

    The object's Name field, and only that. Same name means probable duplicate
    is a claim a business will accept; same value in some other groupable
    column is not. When Name is an auto-number — as it is on every OrgIQ object
    — it is not groupable, and the honest answer is that this org gives us no
    duplicate signal for that object, not that some other column will do."""
    for f in desc.get("fields", []):
        if f.get("nameField") and f.get("groupable") and f.get("type") in ("string", "combobox"):
            return f.get("name")
    return ""


def collect_record_stats(client: _Client, objects, sample_fields: int = FILL_SAMPLE_FIELDS,
                         dup_ceiling: int = DUP_SCAN_CEILING) -> list:
    """Real fill rate, staleness and duplicate signal for D2.

    This is the first D2 input that is measured rather than generated, so the
    definitions matter and are stated rather than implied:

      fill_rate      mean, over a bounded sample of the object's own fields, of
                     the share of records where the field is not null. Sampled
                     fields are listed on the RecordStats.
      stale_ratio    share of records whose LastModifiedDate is older than 24
                     months. Modification, not creation — a record nobody has
                     touched in two years is what the rule is about.
      duplicate_rate surplus records sharing a Name value, over the total:
                     sum(group size - 1) / total. Two rows named the same
                     contribute one duplicate, not two.

    Every probe is a COUNT() or an aggregate; no row is ever fetched. Cost is
    3 + len(sample) queries per object plus one describe. The duplicate
    aggregate is the only one that touches every row, so it is skipped above
    `dup_ceiling` and the skip is recorded on the object rather than silently
    producing 0.0.

    A sub-signal that fails leaves its ratio at the benign default AND names
    itself in RecordStats.unavailable — the D2 rules cannot read that field, but
    the report can, and a 1.0 fill rate that nobody measured never gets to look
    like a clean bill of health."""
    stats, skipped = [], []
    for obj in objects:
        try:
            total = client.count("SELECT COUNT() FROM " + obj)
        except SfError as exc:
            skipped.append(obj + " (not queryable: " + str(exc) + ")")
            continue
        if total == 0:
            skipped.append(obj + " (no records)")
            continue

        try:
            desc = client.describe(obj)
        except SfError as exc:
            skipped.append(obj + " (describe failed: " + str(exc) + ")")
            continue

        unavailable, notes = [], []

        # -- fill rate
        sample = _fill_candidates(desc, sample_fields)
        populated, probed = [], []
        for name in sample:
            try:
                n = client.count("SELECT COUNT() FROM " + obj + " WHERE " + name + " != null")
            except SfError as exc:
                client.gap("fill probe failed on " + name + " — " + str(exc), obj)
                continue
            populated.append(n / float(total))
            probed.append(name)
        if probed:
            fill = sum(populated) / len(populated)
        else:
            fill = 1.0
            unavailable.append("fill_rate")
            notes.append("no field on this object could be probed for population")

        # -- staleness
        try:
            stale_n = client.count("SELECT COUNT() FROM " + obj
                                   + " WHERE LastModifiedDate < LAST_N_MONTHS:"
                                   + str(STALE_MONTHS))
            stale = stale_n / float(total)
        except SfError as exc:
            stale = 0.0
            unavailable.append("stale_ratio")
            notes.append("staleness query failed — " + str(exc))

        # -- duplicates
        dup, dup_key, uniq = 0.0, _dup_key(desc), 1.0
        if not dup_key:
            unavailable.append("duplicate_rate")
            notes.append("the Name field is not groupable (auto-number or "
                         "encrypted), so this org offers no duplicate signal here")
        elif total > dup_ceiling:
            unavailable.append("duplicate_rate")
            notes.append(str(total) + " records exceeds the " + str(dup_ceiling)
                         + "-record ceiling for a full-table GROUP BY; probe skipped")
        else:
            try:
                # Is this key an identifier at all?
                #
                # The probe assumes that two records sharing a Name are probably
                # the same thing. That holds for an Account and fails completely
                # for an object whose Name is a category — a role, a line-item
                # type, a junction label — where every repeat is correct. Run
                # against a real org, OrgIQ_Persona__c reported an 89% duplicate
                # rate: 114 rows, 13 role names, zero duplicates, and a
                # High-severity ticket telling someone to merge them.
                #
                # One aggregate settles it, before any grouping is done.
                head = client.rows("SELECT COUNT_DISTINCT(" + dup_key + ") d FROM " + obj)
                distinct = int((head[0] if head else {}).get("d") or 0)
                uniq = (distinct / float(total)) if total else 1.0
            except SfError as exc:
                distinct, uniq = 0, 1.0
                unavailable.append("duplicate_rate")
                notes.append("key-uniqueness probe failed — " + str(exc))

            if "duplicate_rate" in unavailable:
                pass
            elif uniq < md.MIN_KEY_UNIQUENESS:
                unavailable.append("duplicate_rate")
                notes.append(str(distinct) + " distinct " + dup_key + " value(s) across "
                             + str(total) + " record(s) — this object's name is a "
                             "category, not an identifier, so repeats are correct "
                             "and no duplicate signal can be read from it")
            else:
                try:
                    # The grouped VALUE is deliberately not selected. Only the
                    # counts are needed, and `SELECT Name k, COUNT(Id) c` pulled
                    # customer names — account names, policy numbers — across the
                    # API for a number that never used them.
                    rows = client.rows(
                        "SELECT COUNT(Id) c FROM " + obj
                        + " GROUP BY " + dup_key + " HAVING COUNT(Id) > 1 LIMIT "
                        + str(DUP_GROUP_LIMIT))
                    surplus = sum(int(r.get("c") or 0) - 1 for r in rows)
                    dup = surplus / float(total)
                    if len(rows) >= DUP_GROUP_LIMIT:
                        notes.append("duplicate groups truncated at " + str(DUP_GROUP_LIMIT)
                                     + "; the rate is a floor")
                except SfError as exc:
                    unavailable.append("duplicate_rate")
                    notes.append("duplicate aggregate failed — " + str(exc))

        if len(unavailable) == 3:
            # Nothing was measured. Emitting a RecordStats here would put three
            # benign defaults in front of the D2 rules and score the object clean.
            skipped.append(obj + " (no D2 sub-signal could be measured)")
            continue

        stats.append(md.RecordStats(
            object_name=obj, fill_rate=fill, stale_ratio=stale, duplicate_rate=dup,
            record_count=total, sampled_fields=tuple(probed), duplicate_key=dup_key,
            key_uniqueness=uniq,
            unavailable=tuple(unavailable), notes=tuple(notes),
        ))

    if not stats:
        client.miss(md.SIGNAL_RECORD_STATS,
                    "no object yielded a record-level measurement"
                    + ((" — " + "; ".join(skipped[:3])) if skipped else ""))
        for sub in (md.SIGNAL_FILL_RATE, md.SIGNAL_STALENESS, md.SIGNAL_DUPLICATES):
            client.miss(sub, "no record statistics were collected")
        return []

    detail = str(len(stats)) + " object(s) measured"
    if skipped:
        detail += "; " + str(len(skipped)) + " object(s) skipped: " + "; ".join(skipped[:3])
    client.ok(md.SIGNAL_RECORD_STATS, detail)

    # Each measurement is its own signal, because they fail independently and a
    # dimension that inherits all three from "we got some record stats" reports
    # coverage it did not earn. A sub-signal counts as collected if it was taken
    # on at least one object; the objects it was NOT taken on are named, so a
    # partial answer stays visibly partial.
    for sub, attr in ((md.SIGNAL_FILL_RATE, "fill_rate"),
                      (md.SIGNAL_STALENESS, "stale_ratio"),
                      (md.SIGNAL_DUPLICATES, "duplicate_rate")):
        got = [s for s in stats if attr not in s.unavailable]
        lost = [s for s in stats if attr in s.unavailable]
        if not got:
            why = lost[0].notes[-1] if lost and lost[0].notes else "not measurable"
            client.miss(sub, "not measurable on any of the " + str(len(stats))
                        + " object(s) — " + why)
        else:
            note = "measured on " + str(len(got)) + "/" + str(len(stats)) + " object(s)"
            if lost:
                note += "; not measurable on " + ", ".join(s.object_name for s in lost[:5])
            client.ok(sub, note)
    return stats


# ------------------------------------------------------------ discovery

def discover_objects(client: _Client, include_managed: bool = False) -> list:
    """Custom objects worth probing, from EntityDefinition.

    Custom objects only, and custom settings excluded. Standard objects in a
    fresh org carry sample data that says nothing about the customer, and there
    are hundreds of them — an unbounded D2 sweep across every queryable entity
    is exactly the unbounded cost this module promises not to incur. A caller
    with a considered list should pass it instead."""
    soql = ("SELECT QualifiedApiName, IsQueryable, IsCustomSetting, NamespacePrefix "
            "FROM EntityDefinition WHERE IsCustomizable = true AND IsQueryable = true")
    try:
        rows = client.rows(soql, tooling=True)
    except SfError as exc:
        client.gap("EntityDefinition query failed, object list is empty — " + str(exc))
        return []
    out = []
    for r in rows:
        name = r.get("QualifiedApiName") or ""
        if not name.endswith("__c") or r.get("IsCustomSetting"):
            continue
        if r.get("NamespacePrefix") and not include_managed:
            continue
        out.append(name)
    return sorted(out)


# ------------------------------------------------------------- top level

def collect(org: str, objects=None, include_managed: bool = True,
            include_managed_permission_sets: bool = False,
            doc_limit: int = DOC_DESCRIBE_LIMIT, sample_fields: int = FILL_SAMPLE_FIELDS,
            dup_ceiling: int = DUP_SCAN_CEILING, with_field_schema: bool = True,
            timeout: int = DEFAULT_TIMEOUT, verbose: bool = False) -> OrgCollection:
    """Run every collector against `org` and return what came back.

    `include_managed` governs flows, Apex and triggers, where a packaged
    component is still a component an agent can hit. Permission sets have their
    own flag and default the other way — see collect_permission_sets for why.

    Never raises for a partial result — that is the expected outcome. It raises
    only when the CLI itself is missing or the org cannot be reached at all,
    because a scan with no connection is not a partial scan, it is no scan."""
    client = _Client(org, timeout=timeout, verbose=verbose)
    coll = OrgCollection(org=org)

    # Identity first: also the connectivity check. Nothing here is a secret —
    # the org id and name are on every scan record already.
    try:
        rows = client.rows("SELECT Id, Name FROM Organization LIMIT 1")
        if rows:
            coll.org_id = rows[0].get("Id") or ""
            coll.org_name = rows[0].get("Name") or ""
    except SfError as exc:
        raise SfError("cannot reach org '" + org + "': " + str(exc))

    meta = coll.metadata
    meta.flows = collect_flows(client, include_managed)
    meta.apex = collect_apex(client, include_managed)
    meta.triggers = collect_triggers(client, include_managed)
    meta.permission_sets = collect_permission_sets(client, include_managed_permission_sets)
    meta.report_refs = collect_report_refs(client, doc_limit)

    if objects is None:
        objects = discover_objects(client, include_managed=False)
    objects = list(objects)

    if with_field_schema and objects:
        fields = collect_field_schema(client, objects)
        meta.field_count = len(fields)
        coll.fields = fields
    elif with_field_schema:
        client.miss(md.SIGNAL_FIELD_SCHEMA, "no object list to read field metadata for")
        coll.fields = []
    else:
        coll.fields = []

    if objects:
        meta.record_stats = collect_record_stats(client, objects, sample_fields, dup_ceiling)
    else:
        client.miss(md.SIGNAL_RECORD_STATS, "no queryable custom object was discovered")

    # The automation-graph signal covers triggers AND record-triggered flows, so
    # its final state is only knowable once both collectors have run. A trigger
    # query that failed is still a hole even if flows came back.
    _settle_automation_signal(client, meta)

    # Exactly one note per signal carries the collector's verdict; the rest are
    # sub-failures logged with an empty signal name and left out of the log.
    for note in client.notes:
        if note.signal:
            meta.record_signal(note.signal, note.state, note.detail)
    coll.notes = client.notes
    coll.cli_invocations = client.calls
    return coll


def _settle_automation_signal(client: _Client, meta: md.OrgMetadata) -> None:
    """D5 runs off triggers and record-triggered flows together. If the trigger
    query failed but flows came back with record-triggered members, the graph is
    partial, not absent — say so, and let it count, because the collision rules
    can still fire on the flow side."""
    trigger_note = next((n for n in client.notes
                         if n.signal == md.SIGNAL_TRIGGERS_FLOWS), None)
    rt_flows = [f for f in meta.flows if f.is_record_triggered]
    if trigger_note is not None and trigger_note.state == md.UNAVAILABLE and rt_flows:
        trigger_note.state = md.COLLECTED
        trigger_note.detail = ("triggers UNAVAILABLE (" + trigger_note.detail + "); "
                               + str(len(rt_flows)) + " record-triggered flow(s) collected, "
                               "so D5 runs on the flow side only")
    elif trigger_note is not None and trigger_note.state == md.COLLECTED:
        trigger_note.detail += "; " + str(len(rt_flows)) + " record-triggered flow(s)"


# ------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        description="OrgIQ org-mode collector — read a live org over the sf CLI. "
                    "Read-only: this never writes to the target org.")
    ap.add_argument("--org", required=True, help="sf username or alias")
    ap.add_argument("--objects", default=None,
                    help="comma-separated object list for D1/D2 (default: discovered "
                         "custom objects)")
    ap.add_argument("--doc-limit", type=int, default=DOC_DESCRIBE_LIMIT,
                    help="reports/dashboards to describe (default %(default)s)")
    ap.add_argument("--fill-sample", type=int, default=FILL_SAMPLE_FIELDS,
                    help="fields averaged for a fill rate (default %(default)s)")
    ap.add_argument("--dup-ceiling", type=int, default=DUP_SCAN_CEILING,
                    help="record count above which the duplicate probe is skipped "
                         "(default %(default)s)")
    ap.add_argument("--exclude-managed", action="store_true",
                    help="drop managed-package flows, Apex and triggers")
    ap.add_argument("--include-managed-permsets", action="store_true",
                    help="also report managed-package permission sets in D4 "
                         "(off by default: they are vendor-owned and unfixable)")
    ap.add_argument("--no-field-schema", action="store_true",
                    help="skip the D1 field collection")
    ap.add_argument("--findings", action="store_true",
                    help="also run the D2-D5 rule packs over what was collected")
    ap.add_argument("--verbose", action="store_true", help="echo each sf invocation")
    a = ap.parse_args()

    objects = [s.strip() for s in a.objects.split(",") if s.strip()] if a.objects else None
    try:
        coll = collect(a.org, objects=objects, include_managed=not a.exclude_managed,
                       include_managed_permission_sets=a.include_managed_permsets,
                       doc_limit=a.doc_limit, sample_fields=a.fill_sample,
                       dup_ceiling=a.dup_ceiling, with_field_schema=not a.no_field_schema,
                       verbose=a.verbose)
    except SfError as exc:
        sys.exit("org mode failed: " + str(exc))

    print(coll.summary())

    for s in coll.metadata.record_stats:
        print("\nD2 " + s.object_name + ": " + str(s.record_count) + " records, fill "
              + format(s.fill_rate * 100, ".0f") + "% over "
              + (", ".join(s.sampled_fields) or "nothing")
              + ", stale " + format(s.stale_ratio * 100, ".0f") + "%, dup "
              + format(s.duplicate_rate * 100, ".1f") + "%")
        for note in s.notes:
            print("   ! " + note)

    if a.findings:
        import rules_ext
        findings = rules_ext.all_findings(coll.metadata)
        print("\n" + str(len(findings)) + " D2-D5 finding(s) from org-collected metadata:")
        for f in findings:
            print("  " + f.rule_id + " " + f.severity + " " + f.component + " — " + f.evidence)


if __name__ == "__main__":
    main()
