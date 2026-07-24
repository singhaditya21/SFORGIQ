#!/usr/bin/env python3
"""
Grounding metrics — Semantic Density and Context Payload, denominated in tokens.

PRD §5.3 names both metrics but leaves them as prose. This module turns them
into numbers without adding an LLM: everything here is pure, auditable
arithmetic over metadata text, so re-scanning an unchanged org yields identical
figures and any delta between two scans is attributable to the metadata alone.

The token counts are ESTIMATES. They approximate what a model would be charged
for this text; they are not produced by a model tokenizer and must never be
presented as a billed token count. Real model-token accounting arrives only with
the LLM enrichment tier (PRD §5.8). Until then these numbers are for comparison
— before vs after a remediation, org vs org — not for invoicing.
"""

from __future__ import annotations

# Two standard rules of thumb, applied together because neither holds alone:
# chars/4 under-counts text made of many short words, words*1.3 under-counts
# identifier-dense text (`CustomerSegmentationClassification__c` is one word and
# roughly nine tokens). Taking the larger keeps both cases from reading low.
_CHARS_PER_TOKEN = 4.0
_TOKENS_PER_WORD = 1.3

_SPIKE = None


def _spike():
    """orgiq_spike imports scan_result, which imports this module — so the
    shared normalisation vocabulary is fetched on first use, not at import."""
    global _SPIKE
    if _SPIKE is None:
        import orgiq_spike
        _SPIKE = orgiq_spike
    return _SPIKE


def estimate_tokens(text: str) -> int:
    """Estimate how many model tokens `text` would cost.

    Deterministic ESTIMATE, not a tokenizer. The figure is derived from
    normalised word count (orgiq_spike.tokenise, which splits camelCase and
    strips the `__c` suffix) and raw character length, taking whichever of the
    two rules of thumb reads higher. It is stable and comparable across scans;
    it is not what a model would actually bill.
    """
    if not text or not text.strip():
        return 0
    stripped = text.strip()
    by_word = len(_spike().tokenise(stripped)) * _TOKENS_PER_WORD
    by_char = len(stripped) / _CHARS_PER_TOKEN
    return max(1, int(round(max(by_word, by_char))))


def semantic_density(fields) -> float:
    """Share of description words that carry information the field's own
    identity does not already give away (PRD §5.3). Returns 0..1.

    Per described field: normalise the description, then subtract every word
    already present in the label or API name, plus the words too generic to
    disambiguate anything (orgiq_spike.GENERIC). What survives is the
    disambiguating remainder. Fields are pooled — numerator and denominator
    summed across the corpus — so a field with a long description weighs more
    than one with three words.

    A description that merely restates its label scores ~0, which is the whole
    point: description coverage can be driven to 100% while density falls
    (PRD §5.5). Fields with no description are excluded from both sides of the
    ratio — this measures the quality of the text that exists, not how much of
    it there is. Coverage is reported separately. 0.0 if nothing is described.

    Deterministic ESTIMATE: counted in unique normalised words, not in model
    tokens.
    """
    spike = _spike()
    informative = 0
    total = 0
    for f in fields:
        desc = (f.description or "").strip()
        if not desc:
            continue
        words = spike.normalise(desc)
        if not words:
            continue
        identity = spike.normalise(f.label or "") | spike.normalise(f.api_name or "")
        total += len(words)
        informative += len(words - identity - spike.GENERIC)
    return (informative / total) if total else 0.0


def grounding_payload(fields) -> dict:
    """Estimated grounding tokens before and after the D1 fixes the tool already
    recommends. Returns {"current_tokens": int, "remediated_tokens": int}.

    `current_tokens` is the text a retriever carries for these fields today:
    API name + label + description, one blob per field.

    `remediated_tokens` re-estimates the same corpus after two of the tool's own
    plays land:
      - D1.LOW_INFO_DESCRIPTION — a description that only restates its label is
        deleted rather than rewritten. It is payload with no retrieval benefit
        (PRD §5.5), so removing it is the honest floor for that play.
      - D1.SEMANTIC_DUPLICATE — a cluster collapses to its canonical field and
        the rest leave the corpus, which is what that play's remediation says.

    Deliberately NOT modelled: D1.MISSING_DESCRIPTION, because writing a real
    description *adds* tokens while raising density — the objective is two-sided
    (§5.5), not payload-minimising; and D1.NUMBERED_FAMILY, whose play is to
    re-model or re-describe the group, not to delete its members.

    Both figures are deterministic ESTIMATES — see estimate_tokens.
    """
    spike = _spike()
    fields = list(fields)

    current = sum(estimate_tokens(_field_text(f)) for f in fields)

    # Reuse the rules themselves rather than re-deriving their conditions, so
    # the projection can never drift from what the backlog actually tickets.
    restating = {f.component for f in spike.rule_low_information_description(fields)}
    superseded = set()
    for finding in spike.rule_semantic_duplicate(fields):
        names = [n.strip() for n in finding.detail.split("|") if n.strip()]
        obj = finding.component.rsplit(" [", 1)[0]   # component is "<Object> [N fields]"
        superseded.update((obj, n) for n in names[1:])   # names[0] is the canonical field

    remediated = 0
    for f in fields:
        if (f.object_name, f.api_name) in superseded:
            continue
        keep = "" if f"{f.object_name}.{f.api_name}" in restating else f.description
        remediated += estimate_tokens(_field_text(f, keep))

    return {"current_tokens": current, "remediated_tokens": remediated}


def _field_text(field, description=None) -> str:
    """The blob a retriever would index for one field. Pass `description` to
    model a field whose description has been changed or removed."""
    desc = field.description if description is None else description
    parts = [field.api_name or "", field.label or "", desc or ""]
    return " ".join(p.strip() for p in parts if p and p.strip())
