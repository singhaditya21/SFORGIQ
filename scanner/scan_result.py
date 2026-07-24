#!/usr/bin/env python3
"""
Assemble a full OrgIQ scan result from raw Findings — the record set that maps
1:1 onto the Salesforce schema (OrgIQ_Scan__c + OrgIQ_Dimension_Score__c +
OrgIQ_Finding__c) and feeds the dashboard.

Scoring is deterministic and PROVISIONAL (like effort points): the exact weights
are a placeholder until a rubric is calibrated. Bands and gate rules follow
PRD §4.2–§4.3.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import backlog  # sibling module (remediation, effort, gate, external id)

RUBRIC_VERSION = "0.1.0-spike"

# --- scoring weights (PROVISIONAL) ---------------------------------------
_SEV_W = {"Critical": 1.0, "High": 0.7, "Medium": 0.4, "Low": 0.15}

BANDS = [
    (0, 40, "Not Ready"),
    (41, 60, "Foundational Work Required"),
    (61, 80, "Conditionally Ready"),
    (81, 100, "Ready"),
]

# Which dimensions the spike can actually assess, and why the others can't yet.
# Coverage is the fraction of a dimension's rule set that could run against the
# given input. Source mode with the D1-only spike => D1 fully assessed, the
# rest not assessed (PRD §7.2.4: below-threshold coverage is excluded from the
# composite).
_UNASSESSED = {
    "D2 Data Foundation":
        "record-level data (fill rates, staleness, duplicates) — needs org mode",
    "D3 Action Surface":
        "Flow / Apex / invocable-action metadata not yet analysed",
    "D4 Permission Blast Radius":
        "permission set & profile metadata not yet analysed",
    "D5 Automation Collision":
        "trigger / flow automation graph not yet built",
}


def band_for(score: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= score <= hi:
            return name
    return "Not Ready"


def _fields_in(finding) -> list[str]:
    """Expand a finding to the field API names it implicates. Group findings
    carry the member list in `detail` separated by ' | '."""
    if finding.detail and " | " in finding.detail:
        return [p.strip() for p in finding.detail.split("|") if p.strip()]
    comp = finding.component
    return [comp.split(".")[-1]] if "." in comp else [comp]


def _d1_score(fields, findings) -> int:
    """Grounding-quality score. Blends description quality (can a retriever read
    this schema?) with structural cleanliness (are there cryptic / duplicated /
    numbered fields to trip on?). PROVISIONAL."""
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


def _dimension_rows(fields, findings) -> list[dict]:
    d1 = _d1_score(fields, findings)
    rows = [{
        "dimension": "D1 Grounding Quality",
        "score": d1,
        "rule_coverage": 100.0,          # all 5 source-mode D1 rules ran
        "in_composite": True,
        "assessment_status": "Assessed",
        "missing_signals": "",
    }]
    for dim, missing in _UNASSESSED.items():
        rows.append({
            "dimension": dim,
            "score": None,
            "rule_coverage": 0.0,
            "in_composite": False,
            "assessment_status": "Not Assessed",
            "missing_signals": missing,
        })
    return rows


def _composite(dim_rows) -> tuple[int, bool, str]:
    """Composite over in-composite dimensions, with PRD §4.2 gate caps."""
    scored = [d["score"] for d in dim_rows if d["in_composite"] and d["score"] is not None]
    if not scored:
        return 0, False, "No dimension met the coverage threshold for the composite"
    composite = int(round(sum(scored) / len(scored)))

    gate_applied, reasons = False, []
    # Any in-composite dimension below 30 caps the composite at 70.
    if any(s < 30 for s in scored) and composite > 70:
        composite, gate_applied = 70, True
        reasons.append("a dimension scored below 30 (capped at 70)")
    # (D4 Critical cap not reachable yet — D4 is unassessed in source mode.)
    return composite, gate_applied, "; ".join(reasons)


def _scan_external_id(source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:24]
    return "SCAN-" + (slug or "scan") + "-0001"


def build(fields, findings, source: str, scan_mode: str = "Source",
          now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    dim_rows = _dimension_rows(fields, findings)
    composite, gate_applied, gate_reason = _composite(dim_rows)
    band = band_for(composite)

    scan = {
        "external_scan_id": _scan_external_id(source),
        "target_org": source,
        "scan_mode": scan_mode,
        "rubric_version": RUBRIC_VERSION,
        "composite_score": composite,
        "readiness_band": band,
        "components_scanned": len(fields),
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
            "dimension": f.dimension,               # "D1"
            "severity": f.severity,
            "confidence": f.confidence,
            "component_type": backlog._component_type(f),
            "component_api_name": f.component,
            "evidence": evidence,
            "remediation": play["remediation"],
            "effort_points": play["points"],
            "blast_radius": 0,                       # source mode: no dependency graph
            "emits_to_backlog": backlog.emits_to_backlog(f),
            "rule_maturity": "experimental",
            "status": "Open",
        })

    return {"scan": scan, "dimensions": dim_rows, "findings": finding_rows}


def write_json(result: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
