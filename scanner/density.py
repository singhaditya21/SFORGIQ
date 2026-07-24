#!/usr/bin/env python3
"""
Grounding metrics — Semantic Density and Context Payload, denominated in tokens.

PRD §5.3 names both metrics but leaves them as prose. This module turns them
into numbers without adding an LLM: everything here is pure, auditable
arithmetic over metadata text, so re-scanning an unchanged org yields identical
figures and any delta between two scans is attributable to the metadata alone.

The token counts are ESTIMATES over normalised words and characters. They are
not produced by a model tokenizer and must never be presented as a billed token
count. Real model-token accounting arrives only with the LLM enrichment tier
(PRD §5.8). Until then these numbers are for comparison — before vs after a
remediation, org vs org — not for invoicing.

Nor are they a cost-saving story. Agentforce grounds through RETRIEVAL, not by
injecting the whole schema (PRD §5), so on this surface the price of bloat is
paid in ACCURACY: the more near-identical, uninformative or dead metadata a
retriever carries, the more indistinguishable candidates it has to choose
between. Semantic density says how much of the retrieved text disambiguates
anything; the payload projection says how much of it is pure dead weight that
can go without losing information. Size is the secondary reading, always.
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


REMOVABLE_KEYS = ("restating_descriptions", "duplicate_clusters",
                  "unreferenced_fields")


def grounding_payload(fields, report_refs=None, code_tokens=frozenset()) -> dict:
    """Estimated grounding payload before and after the D1 fixes the tool already
    recommends, plus what each play removes. Returns::

        {"current_tokens": int, "remediated_tokens": int,
         "removable": {"restating_descriptions": int, "duplicate_clusters": int,
                       "unreferenced_fields": int}}

    READ THIS AS AN ACCURACY MEASURE FIRST. Agentforce grounds through
    RETRIEVAL, not by injecting the whole schema, so on the grounding surface
    the cost of bloat is primarily that a retriever has more indistinguishable
    candidates to choose between (PRD §5). What the number below says is how
    much of what it carries is dead weight — payload removable without losing
    any information. Payload size is the secondary story, and none of these
    figures is a billed cost.

    `current_tokens` is the text a retriever carries for these fields today:
    API name + label + description, one blob per field.

    `remediated_tokens` re-estimates the same corpus after three of the tool's
    own plays land:
      - D1.LOW_INFO_DESCRIPTION — a description that only restates its label is
        deleted rather than rewritten. It is payload with no retrieval benefit
        (PRD §5.5), so removing it is the honest floor for that play.
      - D1.SEMANTIC_DUPLICATE — a cluster collapses to its canonical field and
        the rest leave the corpus, which is what that play's remediation says.
      - D1.UNREFERENCED_FIELD — a field no report, dashboard, Flow, Apex class
        or trigger looks at is a retirement candidate, and retiring it removes
        its WHOLE footprint (api name + label + description), not part of it.
        This is the largest of the three levers, and it is the reason
        `report_refs` exists on this signature: the rule is evidence-gated, so
        without report metadata it flags nothing and this play contributes
        nothing. A source tree with no reports must never look like an org
        where every field is dead.

    Deliberately NOT modelled: D1.MISSING_DESCRIPTION, because writing a real
    description *adds* tokens while raising density — the objective is two-sided
    (§5.5), not payload-minimising; and D1.NUMBERED_FAMILY, whose play is to
    re-model or re-describe the group, not to delete its members.

    `removable` attributes the saving so it is not a black box. Its three values
    sum EXACTLY to current_tokens - remediated_tokens: every removable token is
    credited once, to the narrowest play that already removes it. So a field
    that is both dead and label-restating gives its description tokens to
    restating_descriptions and only the remainder to unreferenced_fields — the
    newest lever gets credit for what it alone removes, never for re-labelling a
    saving the older plays had already claimed.

    `code_tokens` is the same Apex/Flow identifier set the D1.UNREFERENCED_FIELD
    rule takes (orgiq_spike.code_identifiers). It is optional but should be
    passed wherever it exists: without it a field referenced only from code
    looks dead here while the backlog correctly leaves it alone, and the
    projection would overstate the saving.

    All figures are deterministic ESTIMATES — see estimate_tokens.
    """
    spike = _spike()
    fields = list(fields)

    # Reuse the rules themselves rather than re-deriving their conditions, so
    # the projection can never drift from what the backlog actually tickets.
    restating = {f.component for f in spike.rule_low_information_description(fields)}
    superseded = set()
    for finding in spike.rule_semantic_duplicate(fields):
        names = [n.strip() for n in finding.detail.split("|") if n.strip()]
        obj = finding.component.rsplit(" [", 1)[0]   # component is "<Object> [N fields]"
        superseded.update((obj, n) for n in names[1:])   # names[0] is the canonical field
    # Returns [] when report_refs is absent or carries no documents — which is
    # what keeps the no-report projection identical to the old two-play one.
    retired = {f.component
               for f in spike.rule_unreferenced_field(fields, report_refs, code_tokens)}

    current = remediated = 0
    removable = dict.fromkeys(REMOVABLE_KEYS, 0)
    for f in fields:
        component = f"{f.object_name}.{f.api_name}"
        full = estimate_tokens(_field_text(f))
        keep = "" if component in restating else f.description
        # What survives deleting a label-restating description. Whole-field
        # removals are credited this residual, so the description tokens are
        # counted under the description play and never twice.
        residual = estimate_tokens(_field_text(f, keep))
        current += full
        removable["restating_descriptions"] += full - residual

        if (f.object_name, f.api_name) in superseded:
            removable["duplicate_clusters"] += residual
        elif component in retired:
            removable["unreferenced_fields"] += residual
        else:
            remediated += residual

    return {"current_tokens": current, "remediated_tokens": remediated,
            "removable": removable}


def _field_text(field, description=None) -> str:
    """The blob a retriever would index for one field. Pass `description` to
    model a field whose description has been changed or removed."""
    desc = field.description if description is None else description
    parts = [field.api_name or "", field.label or "", desc or ""]
    return " ".join(p.strip() for p in parts if p and p.strip())
