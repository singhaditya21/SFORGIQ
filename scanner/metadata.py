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
    directory carries no data.

    The three ratios default to the *benign* value, which is a trap: a default
    fill_rate of 1.0 reads as "this object is perfectly populated" whether we
    measured it or gave up. The trailing provenance fields exist so that never
    goes unsaid — `unavailable` names the sub-signals that were not measured
    and are therefore sitting at their benign default, and `sampled_fields`
    says which fields the fill rate is a mean over. They are additive and
    optional; the D2 rules ignore them, the org-mode report does not."""
    object_name: str
    fill_rate: float = 1.0        # 0..1, key fields populated
    stale_ratio: float = 0.0      # 0..1, not updated in 24 months
    duplicate_rate: float = 0.0   # 0..1
    record_count: int = 0         # rows the ratios were computed over
    sampled_fields: tuple = ()    # fields the fill rate averages
    duplicate_key: str = ""       # field the duplicate probe grouped on
    # How close to unique that key is (distinct values / rows). A duplicate rate
    # is only meaningful when the key identifies a business entity; on an object
    # whose Name is a category — a role, a line-item type, a junction label —
    # every repeat is correct and the "duplicate rate" measures the vocabulary,
    # not the data. 1.0 when not measured.
    key_uniqueness: float = 1.0
    unavailable: tuple = ()       # sub-signals left at their benign default
    notes: tuple = ()             # caveats worth printing next to the numbers


# ------------------------------------------------ persona-facing metadata
#
# What a *person* can do is not one file. A profile grants object and field
# access; a layout decides what they actually see and which buttons they get; a
# flow is a process they can start; an approval process is one they take part
# in; a validation rule is what will stop them. Read together these reconstruct
# a persona's capability surface — and an agent runs as a user, so the agent's
# capability is one of these surfaces.

@dataclass
class LayoutMeta:
    """A page layout — the fields and actions a persona actually sees.

    Field-level security says what a persona *may* read; the layout says what is
    put in front of them. The gap between the two is ordinary, and it matters:
    a field granted but never surfaced is a different remediation decision from
    one on every screen."""
    api_name: str
    object_name: str = ""
    fields: tuple = ()              # api names placed on the layout
    required_fields: tuple = ()
    actions: tuple = ()             # buttons / quick actions exposed
    path: str = ""


@dataclass
class ApprovalStep:
    label: str = ""
    approver_type: str = ""         # Manager | Related User | User | Queue | ...
    approvers: tuple = ()


@dataclass
class ApprovalProcessMeta:
    """The closest thing in metadata to a written-down business process: entry
    criteria, ordered steps, and who signs each one."""
    api_name: str
    object_name: str = ""
    label: str = ""
    active: bool = True
    entry_criteria: str = ""
    steps: tuple = ()               # ApprovalStep
    path: str = ""


@dataclass
class ValidationRuleMeta:
    """What will refuse a persona's save. An agent hitting one mid-conversation
    fails in a way the user cannot act on, so they are part of the action
    surface, not a footnote."""
    api_name: str
    object_name: str = ""
    active: bool = True
    error_message: str = ""
    formula: str = ""
    path: str = ""


@dataclass
class ProfileMeta:
    """A profile, in the same shape as a permission set.

    Salesforce is moving access to permission sets, but every org still has
    profiles and most still carry real grants, so both have to be read. The
    shared shape means the D4 rules do not care which one granted the access —
    only that something did."""
    api_name: str
    label: str = ""
    user_permissions: list = dc_field(default_factory=list)
    object_perms: list = dc_field(default_factory=list)      # ObjectPerm
    layout_assignments: tuple = ()                            # layout api names
    flow_access: tuple = ()                                   # flows this profile may run
    path: str = ""

    def has_perm(self, name: str) -> bool:
        return name in self.user_permissions


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

    def observes_object(self, object_name: str) -> bool:
        """Does any reporting document look at this object at all?

        Documents existing *somewhere* says nothing about an object none of them
        mention — and the difference matters, because "no report references this
        field" only means the field is unused if reports were looking at its
        object in the first place. Otherwise the object is unobserved, and
        treating that as unused condemns a whole schema on no evidence.

        Only qualified `Object.Field` keys count: a bare field name cannot tell
        us which object it belonged to, so it is not proof anyone looked here.
        """
        okey = _leaf(object_name).lower()
        if not okey:
            return False
        prefix = okey + "."
        return any(k.lower().startswith(prefix) for k in self.refs)

    def _reindex(self) -> None:
        self._lower = {k.lower(): k for k in self.refs}


# ------------------------------------------------------- signal registry

# The vocabulary of evidence a scan can carry. Everything downstream — which
# dimensions get scored, what coverage percentage they are scored at, and what
# the report says was missing — is derived from this, not from the --mode flag.
#
# A signal is COLLECTED when we actually consulted its source and know what it
# holds, *even if it holds nothing*; it is UNAVAILABLE when we did not look or
# the look failed. That distinction is the whole point. "The flows query
# succeeded and the org has no autolaunched flow" supports the finding
# D3.NO_SAFE_ACTIONS. "The flows query was rejected" does not — absence of
# evidence is not evidence of absence, and a rule fed an UNAVAILABLE signal
# must not run at all.
SIGNAL_FIELD_SCHEMA      = "metadata.field_schema"
SIGNAL_REPORT_REFERENCES = "usage.report_references"
SIGNAL_RECORD_STATS      = "data.record_stats"
SIGNAL_PERMISSION_SETS   = "permissions.permission_sets"
SIGNAL_FLOWS             = "automation.flows"
SIGNAL_APEX              = "automation.apex_classes"
SIGNAL_TRIGGERS_FLOWS    = "automation.triggers_flows"

# D2's three sub-signals. They exist because "we have record stats" is too
# coarse to be honest: an org whose Name field is an auto-number gives a fill
# rate and a staleness ratio but no duplicate signal at all, and reporting D2
# at full coverage there would claim a duplicate check that never ran. Each is
# gated on data.record_stats as well, so a dimension cannot inherit a
# sub-signal from a collection that did not happen.
SIGNAL_FILL_RATE   = "data.fill_rate"
SIGNAL_STALENESS   = "data.staleness"
SIGNAL_DUPLICATES  = "data.duplicates"

# Reserved for the third-party ingest phase. Named here so the coverage
# arithmetic and the OrgIQ_Finding__c.Source__c picklist agree from the start.
# Nothing sets them yet; a dimension that requires one of them therefore
# reports it as missing, which is the correct answer today.
SIGNAL_OPTIMIZER     = "external.optimizer"
SIGNAL_HEALTHCHECK   = "external.healthcheck"
SIGNAL_CODEANALYZER  = "external.codeanalyzer"

SIGNALS = (
    SIGNAL_FIELD_SCHEMA, SIGNAL_REPORT_REFERENCES, SIGNAL_RECORD_STATS,
    SIGNAL_FILL_RATE, SIGNAL_STALENESS, SIGNAL_DUPLICATES,
    SIGNAL_PERMISSION_SETS, SIGNAL_FLOWS, SIGNAL_APEX, SIGNAL_TRIGGERS_FLOWS,
    SIGNAL_OPTIMIZER, SIGNAL_HEALTHCHECK, SIGNAL_CODEANALYZER,
)

COLLECTED = "collected"
UNAVAILABLE = "unavailable"

# PRD §7.2.4: below this, a dimension is reported as partially assessed and
# kept out of the composite. Exposed here so the scan assembler and the
# dashboard agree on one number.
# Below this, the field the duplicate probe grouped on cannot be an identifier.
# A duplicate rate of R implies a uniqueness of roughly 1-R, so a key at 0.5
# would be claiming that half the org's records are duplicates — which is not a
# data-quality finding, it is evidence that the key is a category. Measured on
# a real org, OrgIQ_Persona__c came back at 0.11: 114 rows, 13 role names, zero
# duplicates, and an 89% "duplicate rate" filed as a High-severity ticket to
# merge them.
MIN_KEY_UNIQUENESS = 0.5

COVERAGE_THRESHOLD = 0.70

ASSESSED = "Assessed"
PARTIALLY_ASSESSED = "Partially Assessed"
NOT_ASSESSED = "Not Assessed"


@dataclass
class SignalStatus:
    """What happened when we went looking for one signal.

    `detail` is the reason a consumer can quote — "Analytics describe returned
    FORBIDDEN for all 30 reports" is a usable sentence in a report; a bare
    False is not. `item_count` is deliberately independent of `state`: a
    collected signal with zero items is a real, useful answer."""
    name: str
    state: str = COLLECTED
    detail: str = ""
    item_count: int = 0

    @property
    def present(self) -> bool:
        return self.state == COLLECTED


@dataclass(frozen=True)
class RuleSignals:
    """What one rule needs before it is allowed to run.

    `all_of` is a conjunction; `any_of` is satisfied by one member. The split
    exists because some rules make a negative claim and some do not:
    D3.NO_SAFE_ACTIONS asserts that *nothing* callable exists, so it needs both
    the flow and the Apex signal or it would indict an org for a gap it never
    looked at. D3.UNDOCUMENTED_ACTION only ever reports on components it can
    see, so either signal alone lets it say something true."""
    dimension: str
    all_of: frozenset = frozenset()
    any_of: frozenset = frozenset()

    def runnable(self, present: frozenset) -> bool:
        if not self.all_of <= present:
            return False
        return not self.any_of or bool(self.any_of & present)

    def missing(self, present: frozenset) -> set:
        gaps = set(self.all_of) - set(present)
        if self.any_of and not (self.any_of & present):
            gaps |= set(self.any_of)
        return gaps


def _needs(dim, *signals, any_of=()):
    return RuleSignals(dim, frozenset(signals), frozenset(any_of))


# Every rule in the packs, with the evidence it depends on. This is the
# declaration the PRD calls for at rule granularity: coverage is not a constant
# any more, it is the fraction of a dimension's rules that could actually run.
RULE_SIGNALS = {
    # D1 — orgiq_spike. Five rules read field metadata alone; the sixth claims a
    # field is unused, which is only sayable once report metadata was read.
    "D1.MISSING_DESCRIPTION":    _needs("D1", SIGNAL_FIELD_SCHEMA),
    "D1.LOW_INFO_DESCRIPTION":   _needs("D1", SIGNAL_FIELD_SCHEMA),
    "D1.CRYPTIC_API_NAME":       _needs("D1", SIGNAL_FIELD_SCHEMA),
    "D1.NUMBERED_FAMILY":        _needs("D1", SIGNAL_FIELD_SCHEMA),
    "D1.SEMANTIC_DUPLICATE":     _needs("D1", SIGNAL_FIELD_SCHEMA),
    "D1.UNREFERENCED_FIELD":     _needs("D1", SIGNAL_FIELD_SCHEMA, SIGNAL_REPORT_REFERENCES),
    # D2 — rules_ext. Record data or nothing, and each rule names the one
    # measurement it reads: an org that yields a fill rate but no duplicate key
    # is assessed for two of the three, not waved through at full coverage.
    "D2.LOW_FILL_RATE":          _needs("D2", SIGNAL_RECORD_STATS, SIGNAL_FILL_RATE),
    "D2.STALE_DATA":             _needs("D2", SIGNAL_RECORD_STATS, SIGNAL_STALENESS),
    "D2.DUPLICATE_RECORDS":      _needs("D2", SIGNAL_RECORD_STATS, SIGNAL_DUPLICATES),
    # D3 — rules_ext.
    "D3.NO_SAFE_ACTIONS":        _needs("D3", SIGNAL_FLOWS, SIGNAL_APEX),
    "D3.UNDOCUMENTED_ACTION":    _needs("D3", any_of=(SIGNAL_FLOWS, SIGNAL_APEX)),
    "D3.INACTIVE_ACTION":        _needs("D3", SIGNAL_FLOWS),
    "D3.APEX_NO_TESTS":          _needs("D3", SIGNAL_APEX),
    # D4 — rules_ext.
    "D4.MODIFY_ALL_DATA":        _needs("D4", SIGNAL_PERMISSION_SETS),
    "D4.VIEW_ALL_DATA":          _needs("D4", SIGNAL_PERMISSION_SETS),
    "D4.WIDE_OBJECT_ACCESS":     _needs("D4", SIGNAL_PERMISSION_SETS),
    "D4.DELETE_GRANTED":         _needs("D4", SIGNAL_PERMISSION_SETS),
    # D5 — rules_ext. The automation graph is one signal: a trigger and the
    # record-triggered flow it collides with come from the same collection step.
    "D5.MULTIPLE_TRIGGERS":      _needs("D5", SIGNAL_TRIGGERS_FLOWS),
    "D5.DML_IN_LOOP":            _needs("D5", SIGNAL_TRIGGERS_FLOWS),
    "D5.SOQL_IN_LOOP":           _needs("D5", SIGNAL_TRIGGERS_FLOWS),
    "D5.NO_RECURSION_GUARD":     _needs("D5", SIGNAL_TRIGGERS_FLOWS),
    "D5.TRIGGER_AND_FLOW":       _needs("D5", SIGNAL_TRIGGERS_FLOWS, SIGNAL_FLOWS),
}

DIMENSIONS = ("D1", "D2", "D3", "D4", "D5")

# D1 is not a member: the D1 scanner owns its own inputs and the caller has
# always decided D1 for itself. Kept out so assessable_dims() means exactly
# what it meant before.
_SCORED_BY_METADATA = ("D2", "D3", "D4", "D5")


@dataclass
class DimensionCoverage:
    """Per-dimension answer to 'how much of this did we actually assess, and
    what stopped us'."""
    dimension: str
    coverage: float                  # 0..1 — runnable rules / total rules
    rules_runnable: int
    rules_total: int
    missing_signals: tuple = ()      # sorted signal names
    reasons: dict = dc_field(default_factory=dict)   # signal -> why it is missing
    blocked_rules: tuple = ()        # sorted rule ids that could not run

    @property
    def assessable(self) -> bool:
        """At least one rule can run. Same bar assessable_dims() has always used."""
        return self.rules_runnable > 0

    @property
    def status(self) -> str:
        if not self.assessable:
            return NOT_ASSESSED
        return ASSESSED if self.coverage >= COVERAGE_THRESHOLD else PARTIALLY_ASSESSED

    @property
    def coverage_pct(self) -> float:
        return round(self.coverage * 100, 1)

    def explain(self) -> str:
        """One sentence a report can print verbatim."""
        head = (self.dimension + " " + self.status.lower() + " at "
                + format(self.coverage_pct, ".1f") + "% rule coverage ("
                + str(self.rules_runnable) + "/" + str(self.rules_total) + " rules)")
        if not self.missing_signals:
            return head
        gaps = []
        for s in self.missing_signals:
            why = self.reasons.get(s)
            gaps.append((s + " (" + why + ")") if why else s)
        return head + " — missing: " + ", ".join(gaps)


@dataclass
class OrgMetadata:
    """Everything the D3/D4/D5 packs need. Empty lists mean 'not available',
    which is what drives the assessed/not-assessed decision.

    `signal_log` is the org-mode upgrade to that rule. Parsing a directory
    cannot tell an empty flows folder from a project that has no flows, so
    source mode infers signal presence from content and always has. A collector
    that talks to an org *does* know the difference, and records it here; an
    explicit entry overrides the inference. Leave it empty and behaviour is
    exactly what it was."""
    flows: list = dc_field(default_factory=list)
    apex: list = dc_field(default_factory=list)
    triggers: list = dc_field(default_factory=list)
    # Persona-facing metadata. Optional and trailing, so every existing caller
    # and every in-memory OrgMetadata keeps working untouched.
    layouts: list = dc_field(default_factory=list)
    profiles: list = dc_field(default_factory=list)
    approval_processes: list = dc_field(default_factory=list)
    validation_rules: list = dc_field(default_factory=list)
    permission_sets: list = dc_field(default_factory=list)
    record_stats: list = dc_field(default_factory=list)
    # Deliberately last: existing callers construct the five lists above.
    report_refs: ReportRefs = dc_field(default_factory=ReportRefs)
    # Trailing and optional, for the same reason.
    signal_log: dict = dc_field(default_factory=dict)    # name -> SignalStatus
    # Field metadata lives with the D1 scanner, not here; this is the one hook
    # that lets D1 coverage be computed from the same registry. Left at 0 and
    # unlogged, D1 correctly reports metadata.field_schema as missing.
    field_count: int = 0

    # ------------------------------------------------------------- signals

    def _measured(self, sub_signal: str) -> bool:
        """Did any object actually yield this D2 sub-measurement? RecordStats
        names the ones it could not take, so this reads the provenance the
        collector left rather than trusting the benign default sitting in the
        field."""
        return any(sub_signal not in (s.unavailable or ()) for s in self.record_stats)

    def _inferred(self) -> dict:
        """Signal presence read off the content, which is all source mode can do."""
        return {
            SIGNAL_FIELD_SCHEMA: self.field_count > 0,
            SIGNAL_REPORT_REFERENCES: self.report_refs.available,
            SIGNAL_RECORD_STATS: bool(self.record_stats),
            SIGNAL_FILL_RATE: self._measured("fill_rate"),
            SIGNAL_STALENESS: self._measured("stale_ratio"),
            SIGNAL_DUPLICATES: self._measured("duplicate_rate"),
            SIGNAL_PERMISSION_SETS: bool(self.permission_sets),
            SIGNAL_FLOWS: bool(self.flows),
            SIGNAL_APEX: bool(self.apex),
            # D5 collides triggers with record-triggered flows; a project of
            # screen flows alone carries no automation graph.
            SIGNAL_TRIGGERS_FLOWS: bool(self.triggers)
            or any(f.is_record_triggered for f in self.flows),
            # Nothing ingests these yet.
            SIGNAL_OPTIMIZER: False,
            SIGNAL_HEALTHCHECK: False,
            SIGNAL_CODEANALYZER: False,
        }

    def record_signal(self, name: str, state: str = COLLECTED,
                      detail: str = "", item_count: int = 0) -> None:
        """State outright what happened to one signal. Collectors call this;
        parsers do not."""
        self.signal_log[name] = SignalStatus(name, state, detail, item_count)

    def present_signals(self) -> frozenset:
        inferred = self._inferred()
        out = set()
        for name in SIGNALS:
            logged = self.signal_log.get(name)
            present = logged.present if logged is not None else inferred[name]
            if present:
                out.add(name)
        return frozenset(out)

    def missing_signals(self) -> frozenset:
        return frozenset(SIGNALS) - self.present_signals()

    def signal_reason(self, name: str) -> str:
        st = self.signal_log.get(name)
        return st.detail if st is not None and not st.present else ""

    # ------------------------------------------------------------ coverage

    def coverage(self, dimension: str = None) -> dict:
        """Per-dimension rule coverage: the fraction of that dimension's rules
        whose required signals were collected, plus the names of the signals
        that stopped the rest. Pass a dimension for one entry."""
        present = self.present_signals()
        dims = [dimension] if dimension else list(DIMENSIONS)
        out = {}
        for dim in dims:
            rules = {rid: r for rid, r in RULE_SIGNALS.items() if r.dimension == dim}
            runnable, blocked, gaps = 0, [], set()
            for rid, r in sorted(rules.items()):
                if r.runnable(present):
                    runnable += 1
                else:
                    blocked.append(rid)
                    gaps |= r.missing(present)
            total = len(rules)
            out[dim] = DimensionCoverage(
                dimension=dim,
                coverage=(runnable / total) if total else 0.0,
                rules_runnable=runnable,
                rules_total=total,
                missing_signals=tuple(sorted(gaps)),
                reasons={s: self.signal_reason(s) for s in sorted(gaps)
                         if self.signal_reason(s)},
                blocked_rules=tuple(blocked),
            )
        return out

    def blocked_rules(self) -> frozenset:
        """Rule ids whose required signals were not collected.

        The registry only *reports* coverage; something still has to stop a
        blocked rule from emitting. A rule that fires on evidence nobody
        gathered is precisely the overclaim the coverage number is there to
        prevent — D3.NO_SAFE_ACTIONS asserting an org exposes nothing callable
        when the Apex it would have checked came back hidden. Callers that
        assemble findings should run them through drop_blocked()."""
        present = self.present_signals()
        return frozenset(rid for rid, r in RULE_SIGNALS.items()
                         if not r.runnable(present))

    def drop_blocked(self, findings) -> tuple:
        """(kept, dropped) — findings partitioned by whether their rule had the
        evidence to run. Unknown rule ids are kept: a rule missing from the
        registry is a registry gap, and silently deleting its findings would be
        a worse failure than reporting them."""
        blocked = self.blocked_rules()
        kept = [f for f in findings if getattr(f, "rule_id", None) not in blocked]
        dropped = [f for f in findings if getattr(f, "rule_id", None) in blocked]
        return kept, dropped

    def assessable_dims(self) -> set:
        """Which dimensions actually have inputs. D1 is decided by the caller
        (it needs fields, which the D1 scanner already parses). Report refs are
        deliberately absent from the decision: they weight existing findings,
        they do not score.

        Now derived from the signal registry rather than four hardcoded
        branches. The answer is unchanged for every input the old code could
        receive — verified exhaustively over the combinations of empty and
        non-empty inputs — with one deliberate exception that only the new
        collector can produce: a RecordStats whose three sub-measurements all
        failed no longer makes D2 assessable. The old code counted the object
        because a RecordStats existed; the object in that state carries three
        benign defaults and nothing measured, and scoring D2 off it would be
        the fabrication this rewrite exists to stop. org_mode never emits such
        a record — it drops the object — so the case is theory, not practice."""
        cov = self.coverage()
        return {d for d in _SCORED_BY_METADATA if cov[d].assessable}


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


def parse_layouts(root: Path) -> list:
    out = []
    for p in root.rglob("*.layout-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
            continue
        fields, required, actions = [], [], []
        for item in r.iter():
            tag = item.tag.split("}")[-1]
            if tag == "field" and item.text:
                fields.append(item.text.strip())
            elif tag in ("customButtons", "quickActionName") and item.text:
                actions.append(item.text.strip())
        # required fields: layoutItems whose behavior is Required
        for li in r.iter():
            if li.tag.split("}")[-1] != "layoutItems":
                continue
            beh = fld = ""
            for ch in li:
                name = ch.tag.split("}")[-1]
                if name == "behavior":
                    beh = (ch.text or "").strip()
                elif name == "field":
                    fld = (ch.text or "").strip()
            if beh == "Required" and fld:
                required.append(fld)
        # Account-Account Layout.layout-meta.xml -> object is the part before "-"
        stem = p.name.replace(".layout-meta.xml", "")
        obj = stem.split("-", 1)[0]
        out.append(LayoutMeta(api_name=stem, object_name=obj,
                              fields=tuple(dict.fromkeys(fields)),
                              required_fields=tuple(dict.fromkeys(required)),
                              actions=tuple(dict.fromkeys(actions)), path=str(p)))
    return out


def parse_approval_processes(root: Path) -> list:
    out = []
    for p in root.rglob("*.approvalProcess-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
            continue
        steps = []
        for st in r.findall("sf:approvalStep", NS):
            approvers = []
            atype = ""
            for ap in st.iter():
                name = ap.tag.split("}")[-1]
                if name == "type" and ap.text:
                    atype = ap.text.strip()
                elif name == "approver" and ap.text:
                    approvers.append(ap.text.strip())
            steps.append(ApprovalStep(label=_text(st, "label"), approver_type=atype,
                                      approvers=tuple(approvers)))
        stem = p.name.replace(".approvalProcess-meta.xml", "")
        out.append(ApprovalProcessMeta(
            api_name=stem, object_name=stem.split(".", 1)[0],
            label=_text(r, "label"),
            active=_text(r, "active").lower() != "false",
            entry_criteria=_text(r, "entryCriteriaBooleanFilter"),
            steps=tuple(steps), path=str(p)))
    return out


def parse_validation_rules(root: Path) -> list:
    out = []
    for p in root.rglob("*.validationRule-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
            continue
        obj = "Unknown"
        parts = p.parts
        if "objects" in parts:
            i = parts.index("objects")
            if i + 1 < len(parts):
                obj = parts[i + 1]
        out.append(ValidationRuleMeta(
            api_name=p.name.replace(".validationRule-meta.xml", ""),
            object_name=obj,
            active=_text(r, "active").lower() != "false",
            error_message=_text(r, "errorMessage"),
            formula=_text(r, "errorConditionFormula"), path=str(p)))
    return out


def parse_profiles(root: Path) -> list:
    out = []
    for p in root.rglob("*.profile-meta.xml"):
        try:
            r = ET.parse(p).getroot()
        except (ET.ParseError, OSError):
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
                view_all=_text(op, "viewAllRecords").lower() == "true"))
        layouts = tuple(_text(la, "layout") for la in r.findall("sf:layoutAssignments", NS)
                        if _text(la, "layout"))
        flows = tuple(_text(fa, "flow") for fa in r.findall("sf:flowAccesses", NS)
                      if _text(fa, "enabled").lower() == "true")
        out.append(ProfileMeta(
            api_name=p.name.replace(".profile-meta.xml", ""),
            label=_text(r, "label") or p.name.replace(".profile-meta.xml", ""),
            user_permissions=perms, object_perms=objs,
            layout_assignments=tuple(dict.fromkeys(layouts)),
            flow_access=flows, path=str(p)))
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
        layouts=parse_layouts(root),
        profiles=parse_profiles(root),
        approval_processes=parse_approval_processes(root),
        validation_rules=parse_validation_rules(root),
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
