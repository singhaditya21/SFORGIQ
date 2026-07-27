#!/usr/bin/env python3
"""
Assemble a full OrgIQ scan result from raw Findings — the record set that maps
1:1 onto the Salesforce schema (OrgIQ_Scan__c + OrgIQ_Dimension_Score__c +
OrgIQ_Finding__c) and feeds the dashboard.

Which dimensions are scored depends on what the caller could actually assess.
Two inputs decide it, and they answer different questions:

  `assessed_dims`  which dimensions the caller looked at at all;
  `coverage`       a {dimension -> metadata.DimensionCoverage} map — how much of
                   each one it actually got to, computed from the signal registry
                   in scanner/metadata.py.

`coverage` is what makes PRD §7.2.4 real. Until it existed, every assessed
dimension was written out at a hardcoded 100.0% rule coverage and the
"Partially Assessed" picklist value on OrgIQ_Dimension_Score__c was never
emitted by anything. Now the number is the fraction of that dimension's rules
whose required signals were genuinely collected, the missing-signal text names
the signals that stopped the rest, and a dimension under
`metadata.COVERAGE_THRESHOLD` (70%) is reported as **Partially Assessed**,
carries no score, and is excluded from the composite.

Suppressing the score of a partially assessed dimension is deliberate. Every
D2–D5 score is `100 - penalties`, so a rule that could not run cannot penalise:
a partial assessment always reads HIGH, and publishing that number would turn a
signal we failed to collect into a good grade. Coverage, status and the missing
signals are published in its place, which is the honest form of the same row.

A caller that supplies no `coverage` map keeps the old behaviour — its
`assessed_dims` are scored and reported as Assessed — because it has told us
nothing about what it collected. Both in-tree callers supply one.

Scoring is deterministic and PROVISIONAL: exact weights are placeholders until
a rubric is calibrated. Bands and gate rules follow PRD §4.2–§4.3.

The scan record also carries the §5.3 grounding metrics (semantic density and
the before/after context payload). Those are ESTIMATES computed by
scanner/density.py from metadata text — no tokenizer, no model — so the field
names keep the `est_` prefix and nothing here should be read as a billed
token count.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import backlog  # sibling module (remediation, effort, gate, external id)
import density  # sibling module (deterministic grounding estimates)
import effort as effort_mod  # evidence-responsive effort + calibration loop
import persona as persona_mod  # capability surfaces + blast radius
import rubric  # the judgement half: bands, penalties, playbook
import metadata as sfmeta  # signal registry: coverage threshold + status vocabulary

# From scanner/rubric.json, so a rubric change and the version stamped on the
# scans it produced cannot get out of step.
RUBRIC_VERSION = rubric.RUBRIC_VERSION

# A scan of a single org, with nobody having said which enterprise it belongs
# to, still belongs to one. Naming it explicitly keeps every record inside the
# tenant boundary rather than leaving a class of rows outside it.
DEFAULT_ENTERPRISE_ID = "ENT-default"
DEFAULT_ENTERPRISE_NAME = "This enterprise"

# Which tool produced a finding. Everything this scanner emits is "OrgIQ"; the
# field exists so findings imported from Optimizer / Health Check / Code
# Analyzer can share the record set without a schema change.
DEFAULT_FINDING_SOURCE = "OrgIQ"

BANDS = rubric.BANDS

_DIM_FULL = {
    "D1": "D1 Grounding Quality",
    "D2": "D2 Data Foundation",
    "D3": "D3 Action Surface",
    "D4": "D4 Permission Blast Radius",
    "D5": "D5 Automation Collision",
}
_DIM_ORDER = ["D1", "D2", "D3", "D4", "D5"]

# Why a dimension can't be scored from a bare SFDX directory (source mode).
_MISSING = {
    "D2": "record-level data (fill rates, staleness, duplicates) — needs org mode",
    "D3": "Flow / Apex / invocable-action metadata not yet analysed",
    "D4": "permission set & profile metadata not yet analysed",
    "D5": "trigger / flow automation graph not yet built",
}

# Penalty per finding for the D2–D5 dimensions (PROVISIONAL) — rubric, not
# engine, so it lives in scanner/rubric.json with the rest of the judgement.
_PENALTY = rubric.PENALTY

# OrgIQ_Dimension_Score__c.Missing_Signals__c is Text(255). Clipped here rather
# than in the loader so the JSON and the Salesforce record say the same thing.
MISSING_SIGNALS_MAX = 255


def band_for(score: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= score <= hi:
            return name
    return "Not Ready"


def _fields_in(finding) -> list:
    if finding.detail and " | " in finding.detail:
        return [p.strip() for p in finding.detail.split("|") if p.strip()]
    comp = finding.component
    return [comp.split(".")[-1]] if "." in comp else [comp]


def _d1_score(fields, findings) -> int:
    """Grounding-quality score: description quality blended with structural
    cleanliness (cryptic / duplicated / numbered fields). PROVISIONAL."""
    total = max(1, len(fields))
    described = sum(1 for f in fields if f.description.strip())
    low_info = sum(1 for f in findings if f.rule_id == "D1.LOW_INFO_DESCRIPTION")
    effective_coverage = max(0.0, (described - low_info) / total)

    implicated = set()
    for f in findings:
        if f.rule_id in ("D1.CRYPTIC_API_NAME", "D1.SEMANTIC_DUPLICATE",
                          "D1.NUMBERED_FAMILY"):
            implicated.update(_fields_in(f))
    structural_clean = 1.0 - min(1.0, len(implicated) / total)

    w = rubric.D1_WEIGHTS
    score = 100 * (w["description_coverage"] * effective_coverage
                   + w["structural_cleanliness"] * structural_clean)
    return int(round(max(0.0, min(100.0, score))))


def _penalty_score(dim_findings) -> int:
    pen = sum(_PENALTY.get(f.severity, 5) for f in dim_findings)
    return int(round(max(0.0, min(100.0, 100 - pen))))


def _clip(text: str, limit: int = MISSING_SIGNALS_MAX) -> str:
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _missing_text(cov) -> str:
    """What stopped this dimension being fully assessed, in one field's worth of
    text: the signal names, each with the collector's own reason where it left
    one, then the rules that consequently did not run. "" when nothing was
    missing.

    Written for every dimension with a gap, not only the ones that fell under
    the threshold. A dimension assessed at 83% is still a dimension one rule
    never ran for, and the row has to be able to say which."""
    bits = []
    for signal in cov.missing_signals:
        why = cov.reasons.get(signal)
        bits.append((signal + " (" + why + ")") if why else signal)
    text = ", ".join(bits)
    if cov.blocked_rules:
        text = (text + "; " if text else "") + \
            str(len(cov.blocked_rules)) + " rule(s) not run: " + \
            ", ".join(cov.blocked_rules)
    return _clip(text)


def _scoreable(findings) -> list:
    """Findings that may move a dimension score.

    Imported late: scanner/external.py reads `Finding` out of the D1 scanner,
    which imports this module, so a top-level import would close the cycle. A
    tree without external.py (or a caller that never ingested a third-party
    result) scores every finding, which is what it did before the module
    existed."""
    try:
        import external
    except ImportError:
        return list(findings)
    return external.scoreable(findings)


def _dimension_rows(fields, findings, assessed, coverage=None) -> list:
    scoreable_all = _scoreable(findings)
    by_dim = {}
    for f in scoreable_all:
        by_dim.setdefault(f.dimension, []).append(f)

    rows = []
    for code in _DIM_ORDER:
        full = _DIM_FULL[code]
        cov = (coverage or {}).get(code)

        if cov is None:
            # No signal inventory was supplied, so the caller's own list is all
            # we know. Unchanged behaviour, including the 100.0 — it means "not
            # measured", and only a caller that measured nothing gets it.
            if code in assessed:
                score = _d1_score(fields, scoreable_all) if code == "D1" \
                    else _penalty_score(by_dim.get(code, []))
                rows.append({
                    "dimension": full, "score": score, "rule_coverage": 100.0,
                    "in_composite": True, "assessment_status": sfmeta.ASSESSED,
                    "missing_signals": "",
                })
            else:
                rows.append({
                    "dimension": full, "score": None, "rule_coverage": 0.0,
                    "in_composite": False, "assessment_status": sfmeta.NOT_ASSESSED,
                    "missing_signals": _MISSING.get(code, ""),
                })
            continue

        # The registry is authoritative about how much ran; `assessed` can only
        # narrow it further (a caller that did not look at a dimension at all).
        status = cov.status if code in assessed else sfmeta.NOT_ASSESSED
        gaps = _missing_text(cov)
        row = {
            "dimension": full,
            "score": None,
            "rule_coverage": cov.coverage_pct,
            "in_composite": status == sfmeta.ASSESSED,
            "assessment_status": status,
            # The static sentence is the last resort: it only says what source
            # mode cannot do, and the registry says what THIS scan could not.
            "missing_signals": gaps or ("" if status == sfmeta.ASSESSED
                                        else _MISSING.get(code, "")),
        }
        if status == sfmeta.ASSESSED:
            row["score"] = _d1_score(fields, scoreable_all) if code == "D1" \
                else _penalty_score(by_dim.get(code, []))
        rows.append(row)
    return rows


def _composite(dim_rows, findings) -> tuple:
    """Mean over in-composite dimensions, with PRD §4.2 gate caps."""
    scored = [d["score"] for d in dim_rows if d["in_composite"] and d["score"] is not None]
    if not scored:
        return 0, False, "No dimension met the coverage threshold for the composite"
    composite = int(round(sum(scored) / len(scored)))

    caps, reasons = [], []
    # Over the scoreable findings only, for the same reason the dimension scores
    # are: a Health Check risk is reported and ticketed under D4 but does not
    # redefine what D4 measures, and the gate is part of that arithmetic.
    #
    # Which caps exist and what they are worth is rubric; *when* each one fires
    # is engine, and stays here as a named condition the data refers to. A cap
    # whose condition this file does not implement is ignored rather than
    # silently treated as met — a rubric edit must not be able to invent a cap.
    triggered = {
        "critical_d4_finding": any(f.dimension == "D4" and f.severity == "Critical"
                                   for f in _scoreable(findings)),
        "any_dimension_below_30": any(s < 30 for s in scored),
    }
    for cap in rubric.GATE_CAPS:
        if triggered.get(cap["when"]):
            caps.append(cap["cap"])
            reasons.append(cap["reason"])

    gate_applied = False
    if caps and min(caps) < composite:
        composite = min(caps)
        gate_applied = True
    return composite, gate_applied, "; ".join(reasons) if gate_applied else ""


def _org_slug(source: str) -> str:
    """A readable, and unique, slug.

    Truncation alone is not safe: an estate names its sandboxes off a common
    prefix, so "Meridian Insurance · dev-core" and "· dev-claims" both cut to
    the same 24 characters and two orgs collapse into one id. When the name is
    cut, a short digest of the whole name goes back on the end — the readable
    part is still readable, and what distinguishes the two orgs survives.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-") or "org"
    if len(slug) <= 24:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:6]
    return slug[:24].rstrip("-") + "-" + digest


def _org_external_id(source: str) -> str:
    return "ORG-" + _org_slug(source)


def _scan_external_id(source: str, now: datetime) -> str:
    """One scan per org per day.

    It used to be a hardcoded `-0001`, so every re-scan overwrote the last one
    and an org could never have a history — which makes a burn-down impossible
    to show. Dating it keeps re-running the same scan idempotent (the common
    case, and what the finding lifecycle relies on) while letting tomorrow's run
    stand as its own record next to today's.
    """
    return "SCAN-" + _org_slug(source) + "-" + now.strftime("%Y%m%d")


# Sandboxes are conventionally named after where they sit; when a caller does
# not tell us the type, the name is the only evidence available. Ordered, because
# "uat-dev" should read as a developer sandbox, not as UAT.
_TYPE_HINTS = [
    ("Production", ("prod", "production", "org of record")),
    ("Developer", ("dev", "developer", "scratch")),
    ("QA", ("qa", "test", "sit")),
    ("UAT", ("uat", "acceptance")),
    ("Staging", ("stage", "staging", "preprod", "pre-prod", "hotfix")),
    ("Training", ("train", "training", "demo", "sandbox-demo")),
]


def infer_org_type(name: str) -> str:
    """Best guess at an org's place in the promotion path from its name.

    A guess, and treated as one: the collector or the caller should override it
    wherever the real type is known. Defaults to Other rather than Production,
    because mislabelling a sandbox as the org of record would inflate the
    severity of everything found in it.
    """
    low = (name or "").lower()
    for org_type, hints in _TYPE_HINTS:
        if any(h in low for h in hints):
            return org_type
    return "Other"


def _group_size(f) -> int:
    """Members in a clustered finding. Group rules carry them in `detail`,
    separated by ' | '; everything else is one component."""
    if f.detail and " | " in f.detail:
        return len([p for p in f.detail.split("|") if p.strip()])
    return 1


def _est(f, base_points, blast, org_type):
    return effort_mod.estimate(
        f.rule_id, base_points,
        blast=(persona_mod.radius_for(f.component, blast) if blast else 0),
        group_size=_group_size(f), org_type=org_type)


def finding_rows(findings, scan_external_id: str, blast=None,
                 org_type: str = "") -> list:
    """Shape raw Findings into loadable finding records.

    Split out of build() because drift findings cannot exist when build()
    runs: they compare an org against the rest of its estate, so they are
    produced once every org has been scanned. They still have to be shaped
    identically — one row builder, or the two paths drift apart.

    `blast` is scanner/persona.blast_index() — how many reports, layouts and
    personas depend on each component. Without it every finding carries the 0
    this field held from the first commit, and a backlog can be ordered by
    severity but never by consequence.
    """
    rows = []
    for f in findings:
        play = backlog._play(f.rule_id)
        est = _est(f, play["points"], blast, org_type)
        evidence = f.evidence if not f.detail else f"{f.evidence} — {f.detail}"
        rows.append({
            # Keyed on the SCAN, not the org. A finding is a child of one scan,
            # and now that scan ids carry their date an org holds several — so an
            # org-keyed id would collide the moment two of its scans coexist.
            # Re-running the same scan is still idempotent, which is what the
            # finding lifecycle relies on: same day, same scan id, same finding id.
            "external_finding_id": backlog._external_id(f, scan_external_id),
            "rule_id": f.rule_id,
            "dimension": f.dimension,
            "severity": f.severity,
            "confidence": f.confidence,
            "component_type": backlog._component_type(f),
            "component_api_name": f.component,
            "evidence": evidence,
            "epic": play["epic"],
            "remediation": play["remediation"],
            # Carried alongside the fix so a record says how the owner knows the
            # work is done — otherwise only the Jira CSV ever shows it.
            "acceptance_criteria": play["acceptance"],
            # The playbook's number is judgement about the RULE; this scan also
            # measured things about this particular finding — how many components
            # depend on it, how many members a cluster has, which org it is in.
            # Those move the estimate. The basis records how, and under which
            # model version, so a recorded actual is never compared against a
            # different model by accident.
            "effort_points": est.points,
            "effort_basis": est.basis,
            # 0 when no dependency index was supplied — which means "not
            # measured", not "nothing depends on this".
            "blast_radius": (persona_mod.radius_for(f.component, blast) if blast else 0),
            # Tool of origin, not the scanned org (that is scan.target_org).
            "source": getattr(f, "source", "") or DEFAULT_FINDING_SOURCE,
            "emits_to_backlog": backlog.emits_to_backlog(f),
            # Who does it. A backlog of a thousand tickets with no owner is a
            # list, and the output of this tool is stated to be a backlog.
            "owner_role": rubric.owner_role(f.rule_id, f.dimension),
            "rule_maturity": "experimental",
            "status": "Open",
        })
    return rows


def build(fields, findings, source: str, scan_mode: str = "Source",
          assessed_dims=frozenset({"D1"}), now: datetime | None = None,
          report_refs=None, code_tokens=frozenset(), coverage=None,
          org_type: str = "", org_overrides: dict = None, blast=None,
          personas=None, enterprise: dict = None) -> dict:
    """`report_refs` / `code_tokens` are the same reference evidence the D1 rules
    run on. They are optional and trail the older arguments so existing callers
    keep working, but a caller that has them should pass them: without them the
    payload projection cannot model retiring unreferenced fields, which is its
    largest lever.

    `coverage` is `metadata.OrgMetadata.coverage()` — the per-dimension record of
    which rules had the evidence to run. Supply it and each dimension is written
    out at its real rule coverage, with the signals that were missing named and
    the §7.2.4 partial-assessment rule applied; omit it and the caller's
    `assessed_dims` is taken at face value, as before.

    `personas` is `persona.build_personas()` — the capability surfaces this scan
    reconstructed. They were already being built (the D4 persona rules and the
    blast index both run on them) and then discarded once their findings were
    out. Passing them here keeps the surface itself, so a reviewer can see the
    personas that are correctly bounded and not only the ones that are not."""
    now = now or datetime.now(timezone.utc)
    dim_rows = _dimension_rows(fields, findings, assessed_dims, coverage)
    composite, gate_applied, gate_reason = _composite(dim_rows, findings)
    band = band_for(composite)

    # Grounding metrics (PRD §5.3). Deterministic ESTIMATES over metadata text —
    # they are for before/after and org/org comparison, never for invoicing, so
    # the token keys stay explicitly prefixed `est_`.
    payload = density.grounding_payload(fields, report_refs, code_tokens)

    # The org this scan is *of*. A scan used to carry only a free-text name, so
    # "the backlog for this org" was a string match and an org had no type, no
    # refresh date and no history. Callers that know better pass `org_type` and
    # `org` overrides; otherwise the name is all the evidence there is.
    org = {
        "external_org_id": _org_external_id(source),
        "name": source,
        "org_type": org_type or infer_org_type(source),
        "instance_url": "",
        "last_refreshed": None,
        "notes": "",
    }
    org.update(org_overrides or {})
    org["is_production"] = org["org_type"] == "Production"

    # The tenant this estate belongs to. A single-install scan has exactly one
    # and does not need to name it, so the default is a single implicit
    # enterprise rather than none — an org with no tenant at all would be a
    # record the isolation predicate could never match, which is worse than a
    # boundary of one.
    ent = enterprise or {"external_enterprise_id": DEFAULT_ENTERPRISE_ID,
                         "name": DEFAULT_ENTERPRISE_NAME, "industry": "", "notes": ""}
    org["enterprise_id"] = ent["external_enterprise_id"]

    scan = {
        "external_scan_id": _scan_external_id(source, now),
        "target_org": source,
        "target_org_external_id": org["external_org_id"],   # links the scan to its org
        "enterprise_id": ent["external_enterprise_id"],
        "scan_mode": scan_mode,
        "rubric_version": RUBRIC_VERSION,
        "composite_score": composite,
        "readiness_band": band,
        "components_scanned": len(fields),
        "semantic_density": density.semantic_density(fields),
        "est_grounding_tokens": payload["current_tokens"],
        "est_remediated_tokens": payload["remediated_tokens"],
        # Additive: what each play removes, so the gap between the two figures
        # above is attributable instead of a black box. The three values sum to
        # that gap. No Salesforce field maps to this yet — the loaders pick
        # their columns explicitly, so carrying it costs them nothing.
        "est_removable_tokens": payload["removable"],
        "gate_applied": gate_applied,
        "gate_reason": gate_reason,
        "scan_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
    }

    return {"enterprise": ent, "org": org, "scan": scan, "dimensions": dim_rows,
            "findings": finding_rows(findings, scan["external_scan_id"], blast,
                                     org["org_type"]),
            # [] when the caller built no personas — which means this scan could
            # not read profile metadata, not that the org has no personas.
            "personas": persona_mod.surface_rows(
                personas or [], scan["external_scan_id"], fields)}


def write_json(result: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
