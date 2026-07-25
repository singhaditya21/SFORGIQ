#!/usr/bin/env python3
"""
OrgIQ spike — D1 Grounding Quality, and the entry point for a whole scan.

Parses an SFDX project directory and runs the deterministic D1 rules, plus the
D2–D5 packs over whatever metadata the run could actually collect. No LLM and
no dependencies beyond the standard library; the `sf` CLI is shelled out to for
org mode and for the free-tool ingest, and neither is required.

THREE MODES, AND THEY NOW MEAN SOMETHING
  Source  parse an SFDX directory. What the repo says the org contains.
  Org     collect from a live org over `sf` (scanner/org_mode.py). What the org
          actually holds, including the record-level data D2 needs and which no
          directory can carry.
  Hybrid  both, merged — see `merge_evidence` for which side wins where.

Until org mode was wired in here, `--mode Org` was a string written onto the
scan record while every byte of evidence still came from disk. It is now a
collector selection, and the mode a scan claims is the mode it ran.

FREE TOOLS
`--code-analyzer` / `--optimizer` ingest a results file from Salesforce's own
free tools, and Security Health Check is read from the org whenever one is
connected (scanner/external.py). Their findings are merged with OrgIQ's,
deduplicated by defect rather than by rule, and every one of them keeps the name
of the engine that raised it.

WHAT A SCAN IS ALLOWED TO CLAIM
Everything collected is recorded in a signal log, and every rule declares the
signals it needs (scanner/metadata.py). A rule whose evidence was not collected
does not run, its findings are withheld if it somehow produced any, and its
dimension's coverage falls accordingly — which is what lets the report say "D1
assessed at 83.3% because usage.report_references was unavailable" instead of
quietly reporting a hardcoded 100%.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import backlog       # sibling module; scanner/ dir is on sys.path when run directly
import density       # semantic density / grounding payload estimates
import metadata as sfmeta  # Flow / Apex / trigger / permission-set parsing (D3–D5)
import scan_result   # sibling module

NS = {"sf": "http://soap.sforce.com/2006/04/metadata"}

# ---------------------------------------------------------------- model

@dataclass
class Field:
    object_name: str
    api_name: str
    label: str
    type: str
    description: str
    help_text: str
    path: str

    @property
    def stem(self) -> str:
        return re.sub(r"__(c|mdt|e)$", "", self.api_name, flags=re.I)


@dataclass
class Finding:
    rule_id: str
    dimension: str
    severity: str
    confidence: str
    component: str
    evidence: str
    detail: str = ""


@dataclass
class Evidence:
    """Everything one scan run collected, and where it came from.

    `meta.signal_log` is the part that matters downstream: it is what turns
    "this scan ran in Org mode" into "these signals were collected, these were
    not, and here is the reason for each"."""
    mode: str
    fields: list = dc_field(default_factory=list)
    meta: "sfmeta.OrgMetadata" = None
    collection: object = None       # org_mode.OrgCollection, when an org was read
    code_tokens: frozenset = frozenset()

    @property
    def coverage(self) -> dict:
        return self.meta.coverage()

    @property
    def assessed_dims(self) -> frozenset:
        """D1 is the caller's call — it is decided by whether fields were read,
        which is a fact this module owns — and D2–D5 come from the registry."""
        d1 = {"D1"} if self.fields else set()
        return frozenset(d1 | self.meta.assessable_dims())


# ------------------------------------------------------------- parsing

def parse_project(root: Path) -> list[Field]:
    fields = []
    for p in root.rglob("*.field-meta.xml"):
        try:
            tree = ET.parse(p)
        except ET.ParseError:
            continue
        r = tree.getroot()

        def get(tag: str) -> str:
            el = r.find(f"sf:{tag}", NS)
            return (el.text or "").strip() if el is not None and el.text else ""

        # .../objects/<Object>/fields/<Field>.field-meta.xml
        obj = "Unknown"
        parts = p.parts
        if "objects" in parts:
            i = parts.index("objects")
            if i + 1 < len(parts):
                obj = parts[i + 1]

        fields.append(Field(
            object_name=obj,
            api_name=get("fullName") or p.stem.replace(".field-meta", ""),
            label=get("label"),
            type=get("type"),
            description=get("description"),
            help_text=get("inlineHelpText"),
            path=str(p),
        ))
    return fields


# ------------------------------------------------------------ collection

MODES = ("Source", "Org", "Hybrid")


def _source_evidence(root: Path) -> Evidence:
    """Parse an SFDX directory: fields for D1, and the Flow / Apex / trigger /
    permission-set / report metadata the other packs read."""
    fields = parse_project(root)
    meta = sfmeta.parse_project(root)
    # The registry has no other way to know D1 has inputs — Field lives here,
    # not in metadata.py. Unset, D1 would report metadata.field_schema missing
    # and score nothing, which is exactly the failure the count exists to avoid.
    meta.field_count = len(fields)
    return Evidence(mode="Source", fields=fields, meta=meta,
                    code_tokens=code_identifiers(meta))


def _org_evidence(target_org: str, collector=None) -> Evidence:
    """Collect from a live org. `collector` is the seam: anything with
    org_mode.collect's signature, so this is testable without an org and a
    caller can swap in a cached collection."""
    if collector is None:
        import org_mode                  # imported here: source mode never needs it
        collector = org_mode.collect
    coll = collector(target_org)
    meta = coll.metadata
    meta.field_count = len(coll.fields)
    return Evidence(mode="Org", fields=list(coll.fields), meta=meta,
                    collection=coll, code_tokens=code_identifiers(meta))


def _by_key(items, key) -> dict:
    return {key(i): i for i in items}


def _prefer(primary, secondary, key=lambda x: x.api_name) -> list:
    """Union of two component lists, primary winning a name collision, ordered
    by name so two runs over unchanged inputs produce identical output."""
    merged = _by_key(secondary, key)
    merged.update(_by_key(primary, key))
    return [merged[k] for k in sorted(merged, key=str)]


def _merge_report_refs(org_refs, src_refs):
    """Reference evidence from both sides, per key by MAX rather than sum.

    The same report can be committed in the repo AND deployed in the org, and
    nothing in either payload says whether two documents are one document. Sum
    would double-count it and inflate blast radius; taking one side whole would
    throw away references we actually read, and a field the other side proves is
    in use would come back out as D1.UNREFERENCED_FIELD. Max is the floor both
    sides agree on: at least this many documents depend on this field.
    `report_count` follows the same rule, so the sentence a finding prints
    ("none of the N documents parsed") is never larger than what was read."""
    if not src_refs.available:
        return org_refs
    if not org_refs.available:
        return src_refs

    out = sfmeta.ReportRefs(
        report_count=max(org_refs.report_count, src_refs.report_count),
        dashboard_count=max(org_refs.dashboard_count, src_refs.dashboard_count),
        refs=dict(org_refs.refs),
    )
    out._reindex()
    for key, n in sorted(src_refs.refs.items()):
        # Through the same case-folded index the parser uses: report metadata
        # writes "Account.Name" and "ACCOUNT.NAME" for one field.
        canon = out._lower.setdefault(key.lower(), key)
        out.refs[canon] = max(out.refs.get(canon, 0), n)
    for name, n in src_refs.dashboard_reports.items():
        out.dashboard_reports[name] = max(
            org_refs.dashboard_reports.get(name, 0), n)
    for name, n in org_refs.dashboard_reports.items():
        out.dashboard_reports.setdefault(name, n)
    return out


def merge_evidence(source: Evidence, org: Evidence) -> Evidence:
    """Hybrid: the repo's committed metadata plus what the org actually holds.

    The org wins every collision, for components and for fields alike. It is the
    system of record — a repo can be behind, ahead, or describing a different
    org entirely — and a Hybrid scan is a scan OF that org. Source contributes
    what the org could not give up: components that failed to collect, and
    report references the Analytics describe endpoint refused or capped.

    Reference evidence is the one thing that accumulates instead of being
    overridden — see `_merge_report_refs`. Losing it is not a smaller claim, it
    is a bigger one: it is how a field the repo proves is in use gets reported
    as used by nothing.

    The signal log is the org's, with one reconciliation: a signal the org
    failed to collect but the source tree supplies is upgraded to collected,
    naming both facts. Without that, a Hybrid scan would report D4 unassessed
    while sitting on a directory full of permission sets."""
    src_meta, org_meta = source.meta, org.meta
    fields = _prefer(org.fields, source.fields,
                     key=lambda f: (f.object_name, f.api_name))

    merged = sfmeta.OrgMetadata(
        flows=_prefer(org_meta.flows, src_meta.flows),
        apex=_prefer(org_meta.apex, src_meta.apex),
        triggers=_prefer(org_meta.triggers, src_meta.triggers),
        permission_sets=_prefer(org_meta.permission_sets, src_meta.permission_sets),
        # Record data has exactly one source: no directory carries rows.
        record_stats=list(org_meta.record_stats),
        report_refs=_merge_report_refs(org_meta.report_refs, src_meta.report_refs),
    )
    merged.field_count = len(fields)
    merged.signal_log = dict(org_meta.signal_log)

    from_source = src_meta.present_signals()
    for name in sfmeta.SIGNALS:
        logged = merged.signal_log.get(name)
        if logged is not None and not logged.present and name in from_source:
            merged.record_signal(
                name, sfmeta.COLLECTED,
                "the org did not yield it (" + logged.detail
                + "); satisfied from the source tree instead")

    # The UNION of both sides' identifiers, not the merged metadata's. A flow
    # collected from the org shadows the repo's copy of the same flow and carries
    # no body — recomputing from the merged list would silently drop the source
    # text and let D1.UNREFERENCED_FIELD call a field dead that a flow we HAD
    # read plainly uses. Reference evidence only ever accumulates.
    return Evidence(mode="Hybrid", fields=fields, meta=merged,
                    collection=org.collection,
                    code_tokens=source.code_tokens | org.code_tokens)


def gather(mode: str, path=None, target_org=None, collector=None) -> Evidence:
    """Collect the evidence one scan runs on, for one mode.

    This is where `--mode` stops being a label. Source parses a directory, Org
    calls the org collector, Hybrid does both and merges. Raises ValueError for
    a mode whose inputs are not there — a scan that silently downgrades to
    source data while recording "Org" on the record is the exact defect this
    replaces."""
    if mode not in MODES:
        raise ValueError("unknown mode " + repr(mode) + "; expected one of "
                         + ", ".join(MODES))
    if mode in ("Source", "Hybrid") and not path:
        raise ValueError(mode + " mode needs an SFDX project path")
    if mode in ("Org", "Hybrid") and not target_org:
        raise ValueError(mode + " mode needs --target-org")

    if mode == "Source":
        return _source_evidence(Path(path))
    if mode == "Org":
        return _org_evidence(target_org, collector)
    return merge_evidence(_source_evidence(Path(path)),
                          _org_evidence(target_org, collector))


# ------------------------------------------------------- free-tool ingest

def ingest_external(evidence: Evidence, code_analyzer=None, optimizer=None,
                    health_check_org=None, workspace=None,
                    run_code_analyzer: bool = False):
    """Run the free-tool adapters and record what each one did on the signal log.

    Returns the `external.ExternalScan`. A tool that produced nothing is logged
    UNAVAILABLE with its own sentence, so "Code Analyzer was not run" and "Code
    Analyzer found nothing" stay distinguishable for the rest of the pipeline —
    that distinction is the whole reason external.ToolResult.ran exists.

    Imported late: external.py reads `Finding` out of this module."""
    import external

    scan = external.collect(code_analyzer_results=code_analyzer,
                            org=health_check_org, optimizer_export=optimizer,
                            workspace=workspace,
                            run_code_analyzer=run_code_analyzer)
    signal_of = {
        external.SOURCE_CODE_ANALYZER: sfmeta.SIGNAL_CODEANALYZER,
        external.SOURCE_HEALTH_CHECK: sfmeta.SIGNAL_HEALTHCHECK,
        external.SOURCE_OPTIMIZER: sfmeta.SIGNAL_OPTIMIZER,
    }
    for result in scan.results:
        name = signal_of.get(result.tool)
        if name:
            evidence.meta.record_signal(
                name, sfmeta.COLLECTED if result.ran else sfmeta.UNAVAILABLE,
                result.detail, result.ingested)
    return scan


# --------------------------------------------------------- normalisation

ABBREV = {
    "acct": "account", "amt": "amount", "addr": "address", "adj": "adjustment",
    "agmt": "agreement", "apt": "appointment", "attr": "attribute", "auth": "authorisation",
    "avg": "average", "bal": "balance", "cat": "category", "cd": "code",
    "cfg": "configuration", "chk": "check", "cnt": "count", "cntct": "contact",
    "co": "company", "cmp": "campaign", "comm": "communication", "conf": "confirmation",
    "cust": "customer", "dept": "department", "desc": "description", "dt": "date",
    "dtl": "detail", "dup": "duplicate", "eff": "effective", "elig": "eligibility",
    "emp": "employee", "err": "error", "est": "estimate", "exp": "expiration",
    "ext": "external", "flg": "flag", "freq": "frequency", "grp": "group",
    "hist": "history", "id": "identifier", "img": "image", "ind": "indicator",
    "info": "information", "init": "initial", "inv": "invoice", "loc": "location",
    "max": "maximum", "min": "minimum", "mgr": "manager", "mo": "month",
    "num": "number", "nbr": "number", "obj": "object", "opp": "opportunity",
    "org": "organisation", "pct": "percent", "pmt": "payment", "prev": "previous",
    "prod": "product", "prof": "profile", "qty": "quantity", "ref": "reference",
    "req": "required", "rev": "revenue", "seg": "segment", "seq": "sequence",
    "src": "source", "stat": "status", "sub": "subscription", "svc": "service",
    "tot": "total", "trans": "transaction", "txn": "transaction", "typ": "type",
    "usr": "user", "val": "value", "ver": "version", "yr": "year",
}

# Tokens describing how a value is ENCODED, not what it MEANS.
# Deliberately narrow: words like number/total/date/amount look like type
# markers but are semantic operators — stripping them makes a count and a
# sum look identical, which is a false-positive generator.
TYPE_MARKERS = {"code", "identifier", "text", "flag", "indicator", "key"}

# Words too generic to establish shared meaning on their own.
GENERIC = {"field", "value", "name", "type", "status", "data", "info",
           "record", "item", "detail", "setting", "option"}

STOP = {"the", "a", "an", "of", "for", "to", "is", "in", "on", "and", "or"}


def tokenise(s: str) -> list[str]:
    s = re.sub(r"__(c|mdt|e)$", "", s, flags=re.I)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    return [t.lower() for t in s.split() if t]


def normalise(s: str) -> frozenset[str]:
    out = set()
    for t in tokenise(s):
        t = re.sub(r"\d+$", "", t)
        if not t or t in STOP:
            continue
        t = ABBREV.get(t, t)
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        out.add(t)
    return frozenset(out)


def meaning(s: str) -> frozenset[str]:
    """Normalised tokens with representation markers removed."""
    return frozenset(normalise(s) - TYPE_MARKERS)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ------------------------------------------------------------- rules

VOWELS = set("aeiouy")


def rule_missing_description(fields: list[Field]) -> list[Finding]:
    out = []
    for f in fields:
        if not f.description.strip():
            out.append(Finding(
                "D1.MISSING_DESCRIPTION", "D1", "Medium", "High",
                f"{f.object_name}.{f.api_name}",
                "no <description> element",
                f"label={f.label!r}",
            ))
    return out


def rule_low_information_description(fields: list[Field]) -> list[Finding]:
    """A description that restates the label carries no disambiguating
    information — it is payload with no retrieval benefit (PRD §5.5)."""
    out = []
    for f in fields:
        d = f.description.strip()
        if not d:
            continue
        dn, ln = normalise(d), normalise(f.label or f.api_name)
        if not dn:
            continue
        # description adds no tokens beyond the label
        if dn <= ln or jaccard(dn, ln) >= 0.85:
            out.append(Finding(
                "D1.LOW_INFO_DESCRIPTION", "D1", "Low", "Medium",
                f"{f.object_name}.{f.api_name}",
                f"description restates label",
                f"label={f.label!r} desc={d[:60]!r}",
            ))
    return out


def rule_cryptic_api_name(fields: list[Field]) -> list[Finding]:
    out = []
    for f in fields:
        stem, toks = f.stem, tokenise(f.api_name)
        reasons = []
        if len(stem) <= 3:
            reasons.append("very short name")
        if re.search(r"\d$", stem) and len(toks) <= 2:
            reasons.append("sequence-numbered name")
        unknown = [t for t in toks
                   if len(t) <= 4 and t not in ABBREV and not (set(t) & VOWELS)]
        if unknown:
            reasons.append(f"vowel-less token(s): {','.join(unknown)}")
        abbrevs = [t for t in toks if t in ABBREV]
        if abbrevs and not f.description.strip():
            reasons.append(f"undocumented abbreviation(s): {','.join(abbrevs)}")
        if reasons:
            out.append(Finding(
                "D1.CRYPTIC_API_NAME", "D1", "Medium",
                "High" if len(reasons) > 1 else "Medium",
                f"{f.object_name}.{f.api_name}",
                "; ".join(reasons),
                f"label={f.label!r}",
            ))
    return out


def _family_key(name: str) -> str:
    """Name with embedded digits removed. Contact1Imported__c and
    Contact2Imported__c share a key; they are a numbered family, not
    a semantic duplicate."""
    return re.sub(r"\d+", "#", re.sub(r"__(c|mdt|e)$", "", name, flags=re.I)).lower()


def rule_numbered_family(fields: list[Field], min_size: int = 2) -> list[Finding]:
    """Repeating numbered field groups. Legitimate as a design choice, but a
    real grounding problem: N near-identical candidates for a retriever to
    choose between, usually with identical descriptions."""
    out = []
    by_obj = defaultdict(lambda: defaultdict(list))
    for f in fields:
        k = _family_key(f.api_name)
        if "#" in k:
            by_obj[f.object_name][k].append(f)
    for obj, fams in by_obj.items():
        for k, fs in fams.items():
            if len(fs) < min_size:
                continue
            out.append(Finding(
                "D1.NUMBERED_FAMILY", "D1", "Medium",
                "High" if len(fs) >= 3 else "Medium",
                f"{obj} [{len(fs)} fields]",
                f"repeating group `{k}`",
                " | ".join(sorted(f.api_name for f in fs)[:6]),
            ))
    return out


def rule_semantic_duplicate(fields: list[Field], threshold: float = 0.85) -> list[Finding]:
    """Two-tier. Tier 1 compares full normalised tokens — a match there is a
    strong signal. Tier 2 compares after stripping encoding markers, which is
    weaker and emits at Low confidence only, and never where the residual
    meaning is degenerate or entirely generic."""
    out = []
    by_obj = defaultdict(list)
    for f in fields:
        by_obj[f.object_name].append(f)

    for obj, fs in by_obj.items():
        sigs = []
        for f in fs:
            full = normalise(f.api_name) | normalise(f.label)
            stripped = meaning(f.api_name) | meaning(f.label)
            if full:
                sigs.append((f, full, stripped))

        seen = set()
        for i in range(len(sigs)):
            fa, fulla, stripa = sigs[i]
            if fa.api_name in seen:
                continue
            tier1, tier2 = [], []
            for j in range(i + 1, len(sigs)):
                fb, fullb, stripb = sigs[j]
                if fb.api_name in seen:
                    continue
                if _family_key(fa.api_name) == _family_key(fb.api_name):
                    continue  # numbered family, handled separately
                if jaccard(fulla, fullb) >= threshold:
                    tier1.append(fb)
                elif (jaccard(stripa, stripb) >= threshold
                      and len(stripa) >= 2
                      and not (stripa <= GENERIC)):
                    tier2.append(fb)

            for group, tier in ((tier1, 1), (tier2, 2)):
                if not group:
                    continue
                names = [fa.api_name] + [g.api_name for g in group]
                for n in names:
                    seen.add(n)
                same_type = len({fa.type} | {g.type for g in group}) == 1
                shared = sorted(fulla if tier == 1 else stripa)
                if tier == 1:
                    conf = "High" if same_type else "Medium"
                    sev = "High" if same_type else "Medium"
                    ev = f"near-identical naming: {{{', '.join(shared)}}}"
                else:
                    conf = "Low"
                    sev = "Medium"
                    ev = f"possible shared meaning after normalisation: {{{', '.join(shared)}}}"
                out.append(Finding(
                    "D1.SEMANTIC_DUPLICATE", "D1", sev, conf,
                    f"{obj} [{len(names)} fields]", ev, " | ".join(names),
                ))
    return out


# ------------------------------------------------------ reference signals

# Anything that could be a field API name in Apex or Flow XML. Field references
# are written `Object__c.Field__c`, and the dot ends the match, so the field name
# lands in the set on its own.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def code_identifiers(meta) -> frozenset:
    """Lowercased identifiers appearing anywhere in Apex, trigger or Flow source.

    Source mode has no MetadataComponentDependency, so the only honest way to
    ask "does anything call this field?" is to look for its API name in the
    files that could call it. Flow XML is re-read from disk because FlowMeta
    keeps no body. Over-matching is deliberate: a name mentioned in a comment
    counts as a reference, so the unreferenced rule errs towards silence.
    """
    bodies = [c.body for c in meta.apex] + [t.body for t in meta.triggers]
    for fl in meta.flows:
        if not fl.path:
            continue
        try:
            bodies.append(Path(fl.path).read_text(errors="replace"))
        except OSError:
            continue
    toks = set()
    for body in bodies:
        toks.update(m.group(0).lower() for m in _IDENT.finditer(body))
    return frozenset(toks)


def rule_unreferenced_field(fields: list[Field], report_refs=None,
                            code_tokens=frozenset()) -> list[Finding]:
    """A custom field nothing looks at — no report, no dashboard, no flow, no
    Apex. It is retirement material: payload a retriever carries and a planner
    has to rule out, for no business reason anyone can point to.

    Evidence-gated twice over, because the failure mode is expensive.

    Globally: with no report or dashboard metadata parsed we cannot tell an
    unused field from an unobserved one, so the rule returns nothing rather than
    declaring the whole org dead.

    And per object: reporting documents existing somewhere in the org says
    nothing about an object none of them mention. A hub org whose only reports
    are the sample ones it shipped with will parse six documents and reference
    not one field on the objects being scanned — and the naive reading of that
    is "100% of your schema is dead weight", which is both false and the fastest
    way to lose an architect's trust. So an object no reporting document touches
    at all is unobserved, not unused, and its fields are left alone.

    Never High confidence either: source mode has no dependency graph, code
    usage is matched textually, and layouts, validation rules, formulas and
    external integrations are invisible from here.
    """
    if report_refs is None or not report_refs.available:
        return []                      # absence of evidence is not evidence of absence

    # With no Apex/Flow source to search, "unreferenced" rests on reports alone,
    # which is a thinner claim again.
    conf = "Medium" if code_tokens else "Low"
    seen_note = ("no Apex or Flow reference" if code_tokens
                 else "no Apex or Flow source available to check")

    # Asked of the reference data, not of `fields`: the caller may be scanning a
    # subset, and an object is observed because a document mentions it, not
    # because the mentioned field happens to be in this batch.
    observed = {}

    out = []
    for f in fields:
        if not re.search(r"__c$", f.api_name, re.I):
            continue                   # standard fields are not ours to retire
        if f.type == "MasterDetail":
            continue                   # structural — retiring it deletes the relationship
        if f.object_name not in observed:
            observed[f.object_name] = report_refs.observes_object(f.object_name)
        if not observed[f.object_name]:
            continue                   # nothing reports on this object — unobserved, not unused
        if report_refs.referenced(f.object_name, f.api_name):
            continue
        if f.api_name.lower() in code_tokens:
            continue
        out.append(Finding(
            "D1.UNREFERENCED_FIELD", "D1", "Medium", conf,
            f"{f.object_name}.{f.api_name}",
            f"not referenced by any of the {report_refs.report_count} "
            f"report/dashboard file(s) parsed; {seen_note}",
            f"label={f.label!r}",
        ))
    return out


RULES = [
    ("D1.MISSING_DESCRIPTION", rule_missing_description),
    ("D1.LOW_INFO_DESCRIPTION", rule_low_information_description),
    ("D1.CRYPTIC_API_NAME", rule_cryptic_api_name),
    ("D1.NUMBERED_FAMILY", rule_numbered_family),
    ("D1.SEMANTIC_DUPLICATE", rule_semantic_duplicate),
    ("D1.UNREFERENCED_FIELD", rule_unreferenced_field),
]

# Rules that consume reference data. Everything else keeps its single-argument
# signature, which is what the tests and scanner/density.py call.
_NEEDS_REFS = {"D1.UNREFERENCED_FIELD"}


# ------------------------------------------------- blast-radius post-pass

# A defect on a field forty reports depend on is the same defect with a far
# larger blast radius. Reports are the cheapest proxy the org gives us for that:
# they are what the business actually looks at.
_BLAST_THRESHOLD = 3          # documents; provisional, like the effort table
_SEV_UP = {"Low": "Medium", "Medium": "High", "High": "High", "Critical": "Critical"}


def _finding_fields(finding) -> list:
    """(object, field) pairs a D1 finding is about. Field-level findings carry
    'Object.Field'; aggregate ones carry 'Object [N fields]' plus a
    pipe-separated detail listing the members."""
    comp = finding.component
    if "[" in comp:
        obj = comp.rsplit(" [", 1)[0]
        return [(obj, n.strip()) for n in finding.detail.split("|") if n.strip()]
    obj, _, fld = comp.rpartition(".")
    return [(obj, fld)] if fld else []


def apply_report_weighting(findings: list[Finding], report_refs) -> list[Finding]:
    """Re-weight D1 findings by how many reports and dashboards depend on the
    field, and say so in the evidence. Mutates and returns `findings`; run once.

    Deliberately a post-pass, not part of the rules. Blast radius has nothing to
    do with *whether* a field is cryptic or duplicated — it is what that costs —
    so it belongs after detection, where it can be re-tuned or dropped without
    touching rule logic.

    Severity climbs one step at the threshold. Confidence climbs at most to
    Medium and only from Low: report usage proves the field is live, which is
    enough to make a speculative finding worth reviewing, never enough to make a
    heuristic certain.
    """
    if report_refs is None or not report_refs.available:
        return findings
    for f in findings:
        # The unreferenced rule is excluded by definition — its findings are the
        # ones with a reference count of zero.
        if f.dimension != "D1" or f.rule_id == "D1.UNREFERENCED_FIELD":
            continue
        counts = [report_refs.referenced(o, n) for o, n in _finding_fields(f)]
        n = max(counts) if counts else 0
        if not n:
            continue
        f.evidence += f"; referenced by {n} report/dashboard file(s)"
        if n >= _BLAST_THRESHOLD:
            f.severity = _SEV_UP.get(f.severity, f.severity)
            if f.confidence == "Low":
                f.confidence = "Medium"
    return findings


def all_d1_findings(fields: list[Field], report_refs=None,
                    code_tokens=frozenset()) -> list[Finding]:
    """Every D1 finding for these fields, blast-radius weighting applied."""
    out = []
    for rule_id, fn in RULES:
        out.extend(fn(fields, report_refs, code_tokens) if rule_id in _NEEDS_REFS
                   else fn(fields))
    return apply_report_weighting(out, report_refs)


@dataclass
class Assembled:
    """The finding set a scan reports, and what was taken out of it on the way."""
    findings: list = dc_field(default_factory=list)
    withheld: list = dc_field(default_factory=list)   # rule had no evidence to run on
    merges: list = dc_field(default_factory=list)     # external.Merge


def assemble_findings(evidence: Evidence, external_scan=None) -> Assembled:
    """Every finding this scan is entitled to report.

    Three steps, in this order and only once:

      1. run the D1 rules and the D2–D5 packs over the collected metadata;
      2. WITHHOLD any finding whose rule did not have its signals. The rule
         packs are pure functions over whatever they are handed and cannot know
         that the Apex query came back refused rather than empty; the registry
         does, and D3.NO_SAFE_ACTIONS asserting that nothing is invocable in an
         org whose Apex we never read is precisely the overclaim the signal log
         exists to stop;
      3. fold in the ingested free-tool findings and merge by defect, so a
         defect two engines both saw is one record and one ticket.

    Merging mutates the surviving findings, which is why this runs once, before
    scoring and before the backlog."""
    import rules_ext                     # late: rules_ext imports Finding from here

    meta = evidence.meta
    findings = all_d1_findings(evidence.fields, meta.report_refs, evidence.code_tokens)
    findings.extend(rules_ext.all_findings(meta))
    kept, withheld = meta.drop_blocked(findings)

    ingested = list(external_scan.findings) if external_scan is not None else []
    if not ingested:
        return Assembled(findings=kept, withheld=withheld)

    import external
    merged, merges = external.merge_findings(kept + ingested)
    return Assembled(findings=merged, withheld=withheld, merges=merges)


# ------------------------------------------------------------- report

# Caption per density.REMOVABLE_KEYS bucket, ordered smallest lever first so the
# table reads up to the one that dominates. Keyed off density's own tuple, so a
# bucket added there fails loudly here rather than being silently dropped.
_REMOVABLE_CAPTIONS = {
    "restating_descriptions":
        "Descriptions that only restate the label — deleted (D1.LOW_INFO_DESCRIPTION)",
    "duplicate_clusters":
        "Fields collapsed into a canonical twin (D1.SEMANTIC_DUPLICATE)",
    "unreferenced_fields":
        "Fields nothing reads — retired entirely (D1.UNREFERENCED_FIELD)",
}


def _coverage_section(evidence: Evidence, withheld=()) -> list:
    """What this scan assessed, at what coverage, and what stopped the rest.

    Printed before the findings on purpose: a reader needs to know a dimension
    was assessed at 67% before reading its finding count, not after."""
    L = ["## Assessment coverage\n"]
    L.append("Mode: **" + evidence.mode + "**. Coverage is the share of a "
             "dimension's rules whose evidence was actually collected — not a "
             "constant, and not an assumption. Below "
             + format(sfmeta.COVERAGE_THRESHOLD * 100, ".0f")
             + "% a dimension is *Partially Assessed*: its findings still stand, "
               "but it publishes no score and stays out of the composite, "
               "because a rule that could not run also could not penalise "
               "(PRD §7.2.4).\n")
    L.append("| Dimension | Status | Rule coverage | Missing signals |")
    L.append("|---|---|---:|---|")
    assessed = evidence.assessed_dims
    for code, cov in sorted(evidence.coverage.items()):
        status = cov.status if code in assessed else sfmeta.NOT_ASSESSED
        gaps = []
        for signal in cov.missing_signals:
            why = cov.reasons.get(signal)
            gaps.append(("`" + signal + "` — " + why) if why else "`" + signal + "`")
        L.append(f"| {code} | {status} | {cov.coverage_pct:.1f}% "
                 f"({cov.rules_runnable}/{cov.rules_total}) | "
                 f"{'; '.join(gaps) or '—'} |")
    L.append("")
    if withheld:
        rules = sorted({f.rule_id for f in withheld})
        L.append(f"{len(withheld)} finding(s) were withheld because their rule's "
                 f"evidence was never collected ({', '.join(rules)}). They are not "
                 f"reported, ticketed or scored — a rule that ran blind has "
                 f"nothing to say.\n")
    return L


def _tools_section(external_scan) -> list:
    """Salesforce's own free tools: what was ingested, and what was not.

    A tool that did not run gets a row saying so. That is the point of the
    section — "Health Check was not read" and "Health Check found nothing" are
    different claims, and a reader must be able to tell them apart."""
    L = ["## Free-tool ingestion\n"]
    L.append("| Tool | State | Detail |")
    L.append("|---|---|---|")
    for r in external_scan.results:
        L.append(f"| {r.tool} | {'ingested' if r.ran else 'not collected'} "
                 f"| {r.detail} |")
    L.append("")
    return L


def report(name: str, fields: list[Field], findings: list[Finding], show: int,
           report_refs=None, code_tokens=frozenset(), evidence=None,
           external_scan=None, withheld=()) -> str:
    L = []
    L.append(f"# OrgIQ spike — {name}\n")
    L.append(f"Fields parsed: **{len(fields)}** across "
             f"**{len({f.object_name for f in fields})}** objects\n")

    if evidence is not None:
        L.extend(_coverage_section(evidence, withheld))
    if external_scan is not None:
        L.extend(_tools_section(external_scan))

    by_rule = defaultdict(list)
    for f in findings:
        by_rule[f.rule_id].append(f)

    L.append("## Summary\n")
    L.append("| Rule | Findings | % of fields |")
    L.append("|---|---:|---:|")
    for rid, _ in RULES:
        n = len(by_rule[rid])
        pct = (n / len(fields) * 100) if fields else 0
        L.append(f"| {rid} | {n} | {pct:.1f}% |")
    L.append("")

    described = sum(1 for f in fields if f.description.strip())
    low_info = len(by_rule["D1.LOW_INFO_DESCRIPTION"])
    # Guarded: an org-mode scan of an org with no custom field still has D2–D5
    # to report, and must not die on a division here.
    total = len(fields) or 1
    L.append(f"Description coverage: **{described}/{len(fields)} "
             f"({described/total*100:.1f}%)** — of which "
             f"**{low_info}** carry no information beyond the label, "
             f"so effective coverage is "
             f"**{(described-low_info)/total*100:.1f}%**\n")

    # Coverage says how much text exists; density says whether it was worth
    # carrying. Both are arithmetic over the metadata — no model is consulted.
    pct = density.semantic_density(fields) * 100
    payload = density.grounding_payload(fields, report_refs, code_tokens)
    cur, rem = payload["current_tokens"], payload["remediated_tokens"]
    shrink = (1 - rem / cur) * 100 if cur else 0.0
    L.append(f"Semantic density: **{pct:.1f}%** — the share of description words "
             f"that add something the field's own label and API name do not "
             f"already say. Deterministic estimate, not a model metric.\n")
    L.append(f"Estimated grounding payload: **{cur:,}** today, **{rem:,}** once "
             f"the plays below land — **{shrink:.1f}%** of it is dead weight. "
             f"Agentforce grounds by *retrieval*, not by injecting the whole "
             f"schema, so read this as an accuracy measure first: it is the "
             f"share of what a retriever carries that can be removed without "
             f"losing any information, and every such token is one more "
             f"near-identical candidate it no longer has to choose between. "
             f"Size is the secondary reading. Deterministic estimates over "
             f"normalised words and characters — not a model tokenizer's count, "
             f"not a bill.\n")

    L.append("| Removable payload | Est. tokens | % of current |")
    L.append("|---|---:|---:|")
    for key in density.REMOVABLE_KEYS:
        n = payload["removable"][key]
        L.append(f"| {_REMOVABLE_CAPTIONS[key]} | {n:,} | "
                 f"{(n / cur * 100) if cur else 0:.1f}% |")
    L.append(f"| **Total removable** | **{cur - rem:,}** | **{shrink:.1f}%** |")
    L.append("")

    if report_refs is not None:
        if report_refs.available:
            L.append(f"Reporting documents parsed: **{report_refs.report_count}** "
                     f"({report_refs.dashboard_count} dashboard(s)). Findings on "
                     f"fields those documents depend on are weighted up — "
                     f"the same defect costs more where the business is looking.\n")
        else:
            L.append("No report or dashboard metadata in this project, so "
                     "D1.UNREFERENCED_FIELD did not run, no finding was "
                     "weighted by blast radius, and the payload projection "
                     "above claims no retirement saving — with nothing to check "
                     "against, an unused field and an unobserved one look the "
                     "same, and the honest projection is the smaller one.\n")

    for rid, _ in RULES:
        fs = by_rule[rid]
        if not fs:
            continue
        L.append(f"## {rid} ({len(fs)})\n")
        L.append("| Component | Confidence | Evidence |")
        L.append("|---|---|---|")
        for f in fs[:show]:
            ev = f.evidence if not f.detail else f"{f.evidence} — `{f.detail[:90]}`"
            L.append(f"| `{f.component}` | {f.confidence} | {ev} |")
        if len(fs) > show:
            L.append(f"| … | | *{len(fs)-show} more* |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="OrgIQ scanner — D1–D5 over an SFDX project, a live org, or "
                    "both. Reads only: nothing here writes to a target org.")
    ap.add_argument("path", nargs="?", default=None,
                    help="SFDX project directory (required for Source and Hybrid)")
    ap.add_argument("--mode", default="Source", choices=list(MODES),
                    help="Source parses the directory; Org collects from a live "
                         "org over the sf CLI; Hybrid merges both (default: %(default)s)")
    ap.add_argument("--target-org", default=None,
                    help="sf username or alias to collect from (required for "
                         "--mode Org and --mode Hybrid)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--backlog", default=None,
                    help="write a Jira-importable backlog CSV to this path "
                         "(threshold-gated: severity>=Medium AND confidence>=Medium)")
    ap.add_argument("--scan-json", default=None,
                    help="write the full scan result (scan + dimension scores + "
                         "findings) as JSON, matching the Salesforce schema")
    ap.add_argument("--code-analyzer", default=None, metavar="FILE",
                    help="a Salesforce Code Analyzer results file (v4 JSON, v5 "
                         "JSON or SARIF) to ingest")
    ap.add_argument("--run-code-analyzer", action="store_true",
                    help="also run `sf code-analyzer run` over the project when "
                         "the plugin is installed; skipped, and said so, when it "
                         "is not")
    ap.add_argument("--optimizer", default=None, metavar="FILE",
                    help="an exported Salesforce Optimizer result file (JSON or "
                         "CSV); Salesforce exposes no API for these")
    ap.add_argument("--skip-health-check", action="store_true",
                    help="do not read Security Health Check from the target org "
                         "(it is read by default in Org and Hybrid mode)")
    a = ap.parse_args()

    if a.path is not None and not Path(a.path).exists():
        sys.exit(f"not found: {a.path}")
    try:
        evidence = gather(a.mode, path=a.path, target_org=a.target_org)
    except ValueError as exc:
        sys.exit(str(exc))
    except RuntimeError as exc:           # org_mode.SfError; already redacted
        sys.exit(f"{a.mode} mode could not collect: {exc}")

    if not evidence.fields and not evidence.meta.present_signals():
        sys.exit("nothing was collected — no field metadata and no other signal")

    # Printed before the free-tool ingest, so this stays a record of what the ORG
    # collector got. Ingestion writes its own signals onto the same log, and a
    # summary printed afterwards would show Health Check in a list headed "org
    # collection" and read as though the collector had fetched it.
    if evidence.collection is not None:
        print(evidence.collection.summary() + "\n")

    # Health Check is read from the org that is being scanned, and only in the
    # modes that actually have one. Ingesting it in Source mode would attribute
    # another org's security posture to a directory.
    hc_org = None if (a.skip_health_check or a.mode == "Source") else a.target_org
    external_scan = ingest_external(
        evidence, code_analyzer=a.code_analyzer, optimizer=a.optimizer,
        health_check_org=hc_org, workspace=a.path,
        run_code_analyzer=a.run_code_analyzer)

    assembled = assemble_findings(evidence, external_scan)
    findings = assembled.findings

    source = a.name or (Path(a.path).name if a.path else a.target_org)
    md = report(source, evidence.fields, findings, a.show,
                evidence.meta.report_refs, evidence.code_tokens,
                evidence=evidence, external_scan=external_scan,
                withheld=assembled.withheld)
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)

    if a.backlog:
        written, observations = backlog.write_csv(findings, source, a.backlog)
        print(f"\nwrote {a.backlog} — {written} backlog item(s) emitted, "
              f"{observations} observation(s) held back by the §4.6 gate "
              f"(severity>=Medium AND confidence>=Medium)")

    if a.scan_json:
        result = scan_result.build(evidence.fields, findings, source,
                                   scan_mode=evidence.mode,
                                   assessed_dims=evidence.assessed_dims,
                                   report_refs=evidence.meta.report_refs,
                                   code_tokens=evidence.code_tokens,
                                   coverage=evidence.coverage)
        scan_result.write_json(result, a.scan_json)
        s = result["scan"]
        partial = [d["dimension"][:2] for d in result["dimensions"]
                   if d["assessment_status"] == sfmeta.PARTIALLY_ASSESSED]
        print(f"\nwrote {a.scan_json} — composite {s['composite_score']} "
              f"({s['readiness_band']}), {len(result['findings'])} findings, "
              f"{len(result['dimensions'])} dimensions"
              + (f"; partially assessed and out of the composite: "
                 f"{', '.join(partial)}" if partial else ""))


if __name__ == "__main__":
    main()
