#!/usr/bin/env python3
"""
OrgIQ spike — D1 Grounding Quality, source mode.

Parses an SFDX project directory and runs four deterministic D1 rules.
No org connection, no LLM, no dependencies beyond the standard library.

Purpose: test whether the D1 rules find anything interesting on real
metadata before committing to the full v0.1 build. Also produces the
first data point for GRND-7 (ambiguity prevalence).
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import backlog  # sibling module; scanner/ dir is on sys.path when run directly

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


RULES = [
    ("D1.MISSING_DESCRIPTION", rule_missing_description),
    ("D1.LOW_INFO_DESCRIPTION", rule_low_information_description),
    ("D1.CRYPTIC_API_NAME", rule_cryptic_api_name),
    ("D1.NUMBERED_FAMILY", rule_numbered_family),
    ("D1.SEMANTIC_DUPLICATE", rule_semantic_duplicate),
]


# ------------------------------------------------------------- report

def report(name: str, fields: list[Field], findings: list[Finding], show: int) -> str:
    L = []
    L.append(f"# OrgIQ spike — {name}\n")
    L.append(f"Fields parsed: **{len(fields)}** across "
             f"**{len({f.object_name for f in fields})}** objects\n")

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
    L.append(f"Description coverage: **{described}/{len(fields)} "
             f"({described/len(fields)*100:.1f}%)** — of which "
             f"**{low_info}** carry no information beyond the label, "
             f"so effective coverage is "
             f"**{(described-low_info)/len(fields)*100:.1f}%**\n")

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
    ap = argparse.ArgumentParser(description="OrgIQ spike — D1 source mode")
    ap.add_argument("path")
    ap.add_argument("--name", default=None)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--backlog", default=None,
                    help="write a Jira-importable backlog CSV to this path "
                         "(threshold-gated: severity>=Medium AND confidence>=Medium)")
    a = ap.parse_args()

    root = Path(a.path)
    if not root.exists():
        sys.exit(f"not found: {root}")

    fields = parse_project(root)
    if not fields:
        sys.exit("no field metadata found")

    findings = []
    for _, fn in RULES:
        findings.extend(fn(fields))

    md = report(a.name or root.name, fields, findings, a.show)
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)

    if a.backlog:
        source = a.name or root.name
        written, observations = backlog.write_csv(findings, source, a.backlog)
        print(f"\nwrote {a.backlog} — {written} backlog item(s) emitted, "
              f"{observations} observation(s) held back by the §4.6 gate "
              f"(severity>=Medium AND confidence>=Medium)")


if __name__ == "__main__":
    main()
