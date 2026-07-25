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

import json
import re
from datetime import datetime, timezone

import backlog  # sibling module (remediation, effort, gate, external id)
import density  # sibling module (deterministic grounding estimates)
import metadata as sfmeta  # signal registry: coverage threshold + status vocabulary

RUBRIC_VERSION = "0.2.0-spike"

# Which tool produced a finding. Everything this scanner emits is "OrgIQ"; the
# field exists so findings imported from Optimizer / Health Check / Code
# Analyzer can share the record set without a schema change.
DEFAULT_FINDING_SOURCE = "OrgIQ"

BANDS = [
    (0, 40, "Not Ready"),
    (41, 60, "Foundational Work Required"),
    (61, 80, "Conditionally Ready"),
    (81, 100, "Ready"),
]

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

# Penalty per finding for the D2–D5 dimensions (PROVISIONAL).
_PENALTY = {"Critical": 29, "High": 15, "Medium": 7, "Low": 2.5}

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

    score = 100 * (0.65 * effective_coverage + 0.35 * structural_clean)
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
    if any(f.dimension == "D4" and f.severity == "Critical" for f in _scoreable(findings)):
        caps.append(60)
        reasons.append("a Critical D4 permission finding caps the composite at 60")
    if any(s < 30 for s in scored):
        caps.append(70)
        reasons.append("a dimension scored below 30 caps the composite at 70")

    gate_applied = False
    if caps and min(caps) < composite:
        composite = min(caps)
        gate_applied = True
    return composite, gate_applied, "; ".join(reasons) if gate_applied else ""


def _scan_external_id(source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:24]
    return "SCAN-" + (slug or "scan") + "-0001"


def build(fields, findings, source: str, scan_mode: str = "Source",
          assessed_dims=frozenset({"D1"}), now: datetime | None = None,
          report_refs=None, code_tokens=frozenset(), coverage=None) -> dict:
    """`report_refs` / `code_tokens` are the same reference evidence the D1 rules
    run on. They are optional and trail the older arguments so existing callers
    keep working, but a caller that has them should pass them: without them the
    payload projection cannot model retiring unreferenced fields, which is its
    largest lever.

    `coverage` is `metadata.OrgMetadata.coverage()` — the per-dimension record of
    which rules had the evidence to run. Supply it and each dimension is written
    out at its real rule coverage, with the signals that were missing named and
    the §7.2.4 partial-assessment rule applied; omit it and the caller's
    `assessed_dims` is taken at face value, as before."""
    now = now or datetime.now(timezone.utc)
    dim_rows = _dimension_rows(fields, findings, assessed_dims, coverage)
    composite, gate_applied, gate_reason = _composite(dim_rows, findings)
    band = band_for(composite)

    # Grounding metrics (PRD §5.3). Deterministic ESTIMATES over metadata text —
    # they are for before/after and org/org comparison, never for invoicing, so
    # the token keys stay explicitly prefixed `est_`.
    payload = density.grounding_payload(fields, report_refs, code_tokens)

    scan = {
        "external_scan_id": _scan_external_id(source),
        "target_org": source,
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

    finding_rows = []
    for f in findings:
        play = backlog._play(f.rule_id)
        evidence = f.evidence if not f.detail else f"{f.evidence} — {f.detail}"
        finding_rows.append({
            "external_finding_id": backlog._external_id(f, source),
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
            "effort_points": play["points"],
            "blast_radius": 0,
            # Tool of origin, not the scanned org (that is scan.target_org).
            "source": getattr(f, "source", "") or DEFAULT_FINDING_SOURCE,
            "emits_to_backlog": backlog.emits_to_backlog(f),
            "rule_maturity": "experimental",
            "status": "Open",
        })

    return {"scan": scan, "dimensions": dim_rows, "findings": finding_rows}


def write_json(result: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
