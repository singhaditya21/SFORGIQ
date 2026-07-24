#!/usr/bin/env python3
"""
Assemble a full OrgIQ scan result from raw Findings — the record set that maps
1:1 onto the Salesforce schema (OrgIQ_Scan__c + OrgIQ_Dimension_Score__c +
OrgIQ_Finding__c) and feeds the dashboard.

Which dimensions are scored depends on what the caller could actually assess
(`assessed_dims`): the real source-mode scanner assesses D1 only; the demo
portfolio assesses all five. Un-assessed dimensions are reported with their
missing signal and excluded from the composite (PRD §7.2.4).

Scoring is deterministic and PROVISIONAL: exact weights are placeholders until
a rubric is calibrated. Bands and gate rules follow PRD §4.2–§4.3.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import backlog  # sibling module (remediation, effort, gate, external id)

RUBRIC_VERSION = "0.2.0-spike"

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


def _dimension_rows(fields, findings, assessed) -> list:
    by_dim = {}
    for f in findings:
        by_dim.setdefault(f.dimension, []).append(f)

    rows = []
    for code in _DIM_ORDER:
        full = _DIM_FULL[code]
        if code in assessed:
            score = _d1_score(fields, findings) if code == "D1" \
                else _penalty_score(by_dim.get(code, []))
            rows.append({
                "dimension": full, "score": score, "rule_coverage": 100.0,
                "in_composite": True, "assessment_status": "Assessed",
                "missing_signals": "",
            })
        else:
            rows.append({
                "dimension": full, "score": None, "rule_coverage": 0.0,
                "in_composite": False, "assessment_status": "Not Assessed",
                "missing_signals": _MISSING.get(code, ""),
            })
    return rows


def _composite(dim_rows, findings) -> tuple:
    """Mean over in-composite dimensions, with PRD §4.2 gate caps."""
    scored = [d["score"] for d in dim_rows if d["in_composite"] and d["score"] is not None]
    if not scored:
        return 0, False, "No dimension met the coverage threshold for the composite"
    composite = int(round(sum(scored) / len(scored)))

    caps, reasons = [], []
    if any(f.dimension == "D4" and f.severity == "Critical" for f in findings):
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
          assessed_dims=frozenset({"D1"}), now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    dim_rows = _dimension_rows(fields, findings, assessed_dims)
    composite, gate_applied, gate_reason = _composite(dim_rows, findings)
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
            "dimension": f.dimension,
            "severity": f.severity,
            "confidence": f.confidence,
            "component_type": backlog._component_type(f),
            "component_api_name": f.component,
            "evidence": evidence,
            "remediation": play["remediation"],
            "effort_points": play["points"],
            "blast_radius": 0,
            "emits_to_backlog": backlog.emits_to_backlog(f),
            "rule_maturity": "experimental",
            "status": "Open",
        })

    return {"scan": scan, "dimensions": dim_rows, "findings": finding_rows}


def write_json(result: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
