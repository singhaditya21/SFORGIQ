#!/usr/bin/env python3
"""
Free-tool ingestion — Salesforce Code Analyzer, Security Health Check, Optimizer.

PRD §2.3 says OrgIQ "defers to Health Check and Code Analyzer; ingests their
output rather than reimplementing it", and §7.3 lists the three as sources.
Until this module existed that was a positioning statement with no code behind
it. This is the code: three adapters that turn a third-party tool's own output
into the same `Finding` objects the rule packs emit, tagged with the tool that
raised them, plus the merge that stops an overlapping defect being counted (and
ticketed) twice.

WHAT THIS MODULE PROMISES

  1. **A tool that did not run contributes nothing.** No file, no plugin, no org
     — the adapter returns zero findings and an honest sentence saying why. It
     never guesses, never treats "not checked" as "clean", and never fails the
     scan. `ToolResult.ran` is the flag a caller reads to decide whether a signal
     was actually collected; a coverage model that wants to say "D4 assessed at
     70% because Health Check was unavailable" reads it from here.

  2. **Provenance survives.** Every ingested finding carries `source` — one of
     the `Source__c` picklist values already deployed on `OrgIQ_Finding__c`
     ("Optimizer", "Health Check", "Code Analyzer") — plus `tool_rule`, the
     tool's own rule name. A Code Analyzer violation must never read as an OrgIQ
     rule result, in the scan JSON, in the backlog CSV, or in the Salesforce
     record. It also means the acceptance criteria can say the honest thing: an
     OrgIQ re-scan cannot clear a Code Analyzer finding, only re-running Code
     Analyzer can.

  3. **Overlap is merged, not stacked.** OrgIQ's D5 loop rules are regex
     heuristics over brace-matched blocks; Code Analyzer has a parser. When both
     describe the same defect on the same component, `merge_findings()` keeps
     one record — the authoritative one — and records that the other engine
     corroborated it. See "Deduplication" below.

SEVERITY IS THE TOOL'S CALL, NOT OURS
  Code Analyzer's numeric severities are mapped faithfully, which means a
  severity-1 security violation lands as a **Critical D4** finding and will trip
  the PRD §4.2 gate that caps the composite at 60. That is deliberate: the gate
  exists so a Ready verdict cannot be issued over an unreviewed critical, and
  the record names Code Analyzer as the engine that made the call, so a reader
  can see whose judgement moved the number.

  The two Code Analyzer JSON generations do *not* share a severity scale (v4 is
  1–3 high→low, v5 is 1–5 critical→info). Mapping both through one table would
  silently promote every v4 "high" to Critical, so they get one table each.

WHAT IS NOT SCORED
  Health Check risks are org-wide *security settings*. OrgIQ's D4 is agent
  permission blast radius, and PRD §2.3 lists "a security scanner" as an
  explicit non-goal — so those findings are reported and ticketed under D4 but
  are excluded from the D4 *score* by `scoreable()`. Letting them move the
  dimension score would quietly redefine what D4 measures. Code Analyzer and
  Optimizer findings are scored: they describe the same code and the same
  metadata the native rules already score, only more reliably.

Standard library only. The `sf` CLI is invoked through subprocess for the org
query and the optional Code Analyzer run; neither is required, and no token is
read, printed or stored by anything here.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import backlog                              # sibling module: the emission rules
from orgiq_spike import Finding

# ------------------------------------------------------------- provenance

SOURCE_ORGIQ = "OrgIQ"
SOURCE_CODE_ANALYZER = "Code Analyzer"
SOURCE_HEALTH_CHECK = "Health Check"
SOURCE_OPTIMIZER = "Optimizer"

# Which engine's word to take when two of them describe the same defect.
# Code Analyzer parses Apex and walks a data-flow graph; Health Check reads the
# org's own settings; Optimizer sees every report, layout and dependency in the
# org. OrgIQ, in source mode, matches regular expressions against committed
# text. Where they disagree, OrgIQ is the one that should yield.
_AUTHORITY = {
    SOURCE_CODE_ANALYZER: 3,
    SOURCE_HEALTH_CHECK: 3,
    SOURCE_OPTIMIZER: 2,
    SOURCE_ORGIQ: 1,
}

_SEV_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
_CONF_RANK = {"High": 3, "Medium": 2, "Low": 1}

# How long we are willing to wait on the `sf` CLI before giving up and
# reporting the signal as uncollected. A hung CLI must not hang a scan.
SF_TIMEOUT = 120
CODE_ANALYZER_TIMEOUT = 900


def source_of(finding) -> str:
    """The engine that raised a finding. Native rule findings carry no `source`
    attribute at all, and they are OrgIQ's."""
    return getattr(finding, "source", "") or SOURCE_ORGIQ


def _finding(rule_id, dimension, severity, confidence, component, evidence,
             detail="", source="", defect_key="", tool_rule="",
             component_type="", reference="") -> Finding:
    """Build the same `Finding` the rule packs emit, then attach the ingestion
    metadata as attributes.

    `Finding` is a plain dataclass owned by the D1 spike; the emitters already
    read `source` off it with `getattr`, so extra attributes ride along without
    a schema change in `scan_result.py`, `backlog.py` or the Salesforce objects.
    """
    f = Finding(rule_id, dimension, severity, confidence, component, evidence, detail)
    f.source = source or SOURCE_ORGIQ
    # Identity of the *defect*, independent of which engine spotted it — the
    # merge key. Defaults to something rule-unique so an unmapped finding can
    # never accidentally merge with anything.
    f.defect_key = defect_key or ("ext:" + rule_id.lower())
    f.tool_rule = tool_rule          # the tool's own rule name, e.g. pmd/AvoidSoqlInLoops
    f.component_type = component_type
    f.reference = reference          # documentation URL, where the tool gives one
    f.corroborated_by = []
    return f


# ----------------------------------------------------------------- results

@dataclass
class ToolResult:
    """What one adapter got, and — just as important — what it did not get.

    `ran` is False whenever the tool's output was unavailable for any reason.
    `detail` is a sentence fit to print in a report or store as a missing-signal
    note; it always says why, because "no findings" and "not checked" are
    different claims and this project does not let them look alike.
    """
    tool: str
    findings: list = dc_field(default_factory=list)
    ran: bool = False
    detail: str = ""
    ingested: int = 0
    unmapped: int = 0
    score: str = ""          # Health Check only: the org's overall score

    @property
    def note(self) -> str:
        return f"{self.tool}: {self.detail}"


@dataclass
class ExternalScan:
    """Every adapter's result for one scan."""
    results: list = dc_field(default_factory=list)

    @property
    def findings(self) -> list:
        out = []
        for r in self.results:
            out.extend(r.findings)
        return out

    def ran(self) -> list:
        return [r.tool for r in self.results if r.ran]

    def missing(self) -> list:
        """(tool, why) for every tool that produced nothing. A coverage model
        turns these into the reason a dimension is only partially assessed."""
        return [(r.tool, r.detail) for r in self.results if not r.ran]

    def notes(self) -> list:
        return [r.note for r in self.results]


# ============================================================ Code Analyzer
#
# Three output shapes are supported because three are in the wild:
#
#   * v5 (`sf code-analyzer run`)  — {"violations": [...]}, severity 1..5.
#   * v4 (`sf scanner run`)        — [{"engine", "fileName", "violations": [...]}],
#                                    severity 1..3.
#   * SARIF 2.1.0                  — the CI-friendly format both can emit.
#
# A results file the caller already has is always preferred: it is what CI
# produced, it needs no plugin, and it needs no JDK. Invocation is opt-in.

# v5: 1 Critical, 2 High, 3 Moderate, 4 Low, 5 Info.
_CA5_SEVERITY = {1: "Critical", 2: "High", 3: "Medium", 4: "Low", 5: "Low"}
# v4: 1 High, 2 Moderate, 3 Low. A different scale — see the module docstring.
_CA4_SEVERITY = {1: "High", 2: "Medium", 3: "Low"}
# SARIF levels.
_SARIF_LEVEL = {"error": "High", "warning": "Medium", "note": "Low", "none": "Low"}


@dataclass
class Violation:
    """One Code Analyzer violation, normalised across output formats."""
    rule: str
    engine: str
    message: str
    file: str
    line: str
    severity: str            # already on OrgIQ's scale
    tags: tuple = ()
    url: str = ""


# Rule name (lowercased) -> (dimension, OrgIQ rule id, defect key).
#
# The defect key is what makes an external finding and a native one collapse
# into one ticket, so it names the DEFECT, not the rule: PMD's
# AvoidDmlStatementsInLoops and OrgIQ's D5.DML_IN_LOOP are the same defect seen
# by two engines.
_CA_RULES = {
    # --- bulk safety: D5 Automation Collision -------------------------------
    "avoiddmlstatementsinloops": ("D5", "D5.EXT_BULK_SAFETY", "dml-in-loop"),
    "operationwithlimitsinloop": ("D5", "D5.EXT_BULK_SAFETY", "dml-in-loop"),
    "avoidsoqlinloops": ("D5", "D5.EXT_BULK_SAFETY", "soql-in-loop"),
    "avoidsoslinloops": ("D5", "D5.EXT_BULK_SAFETY", "soql-in-loop"),
    "avoiddebugstatements": ("D5", "D5.EXT_BULK_SAFETY", "ext:avoiddebugstatements"),
    "avoiddeeplynestedifstmts": ("D5", "D5.EXT_BULK_SAFETY",
                                 "ext:avoiddeeplynestedifstmts"),
    # --- security: D4 Permission Blast Radius -------------------------------
    "apexcrudviolation": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-crud-fls"),
    "apexflsviolation": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-crud-fls"),
    "apexsharingviolations": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-sharing"),
    "apexsoqlinjection": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-soql-injection"),
    "apexinsecureendpoint": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-insecure-endpoint"),
    "apexdangerousmethods": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-dangerous-methods"),
    "apexsuggestusingnamedcred": ("D4", "D4.EXT_SECURITY_VIOLATION",
                                  "apex-named-credential"),
    "apexbadcrypto": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-crypto"),
    "apexopenredirect": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-open-redirect"),
    "apexxssfromescapefalse": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-xss"),
    "apexxssfromurlparam": ("D4", "D4.EXT_SECURITY_VIOLATION", "apex-xss"),
    # --- test quality: D3 Action Surface ------------------------------------
    # An agent-invocable class whose tests assert nothing is, for backlog
    # purposes, the same defect D3.APEX_NO_TESTS describes: nothing establishes
    # that the action works. One ticket, both engines named on it.
    "apexunittestclassshouldhaveasserts": ("D3", "D3.EXT_TEST_QUALITY",
                                           "apex-test-quality"),
    "apexunittestmethodshouldhaveistestannotation": ("D3", "D3.EXT_TEST_QUALITY",
                                                     "apex-test-quality"),
    "apexunittestshouldnotuseseealldatatrue": ("D3", "D3.EXT_TEST_QUALITY",
                                               "apex-test-quality"),
    "apexassertionsshouldincludemessage": ("D3", "D3.EXT_TEST_QUALITY",
                                           "apex-test-quality"),
}

# Fallback for rules not named above, keyed on the violation's category / tags.
# Only the two categories that map onto a dimension OrgIQ actually models.
_CA_CATEGORIES = (
    ("security", ("D4", "D4.EXT_SECURITY_VIOLATION")),
    ("performance", ("D5", "D5.EXT_BULK_SAFETY")),
)


def _ca_dimension(violation) -> tuple:
    """(dimension, rule_id, defect_key) for a violation, or None if OrgIQ has no
    dimension for it.

    Returning None is the point. Roughly half of a default PMD run is code style
    and documentation — real findings, but nothing in the rubric measures them,
    and dropping them into whichever dimension is nearest would move a score on
    a signal the rubric does not model. They are counted as `unmapped` and
    reported, not quietly filed under D5.
    """
    hit = _CA_RULES.get(violation.rule.lower())
    if hit:
        return hit
    haystack = " ".join(violation.tags).lower()
    for needle, (dim, rule_id) in _CA_CATEGORIES:
        if needle in haystack:
            return (dim, rule_id, "ext:{0}:{1}".format(
                violation.engine.lower(), violation.rule.lower()))
    return None


def _basename(path: str) -> str:
    """The component a violation is about. Code Analyzer reports absolute paths;
    a ticket wants `BillingService.cls`, and the merge wants something it can
    line up with a native finding's component."""
    if not path:
        return "unknown"
    return os.path.basename(path.replace("\\", "/").rstrip("/")) or "unknown"


def _component_type_for(name: str) -> str:
    low = name.lower()
    if low.endswith(".cls"):
        return "ApexClass"
    if low.endswith(".trigger"):
        return "ApexTrigger"
    if low.endswith((".js", ".html", ".cmp", ".page", ".component")):
        return "Lightning/Visualforce"
    return "Source file"


def _worst(values, ranks, default) -> str:
    best = default
    for v in values:
        if ranks.get(v, 0) > ranks.get(best, 0):
            best = v
    return best


# ------------------------------------------------------------ format parsers

def _parse_v5(payload) -> list:
    out = []
    for v in payload.get("violations") or []:
        locs = v.get("locations") or []
        idx = v.get("primaryLocationIndex") or 0
        loc = locs[idx] if 0 <= idx < len(locs) else (locs[0] if locs else {})
        try:
            sev = _CA5_SEVERITY.get(int(v.get("severity", 3)), "Medium")
        except (TypeError, ValueError):
            sev = "Medium"
        resources = v.get("resources") or []
        out.append(Violation(
            rule=str(v.get("rule") or ""),
            engine=str(v.get("engine") or ""),
            message=str(v.get("message") or "").strip(),
            file=str(loc.get("file") or ""),
            line=str(loc.get("startLine") or ""),
            severity=sev,
            tags=tuple(str(t) for t in (v.get("tags") or [])),
            url=str(resources[0]) if resources else "",
        ))
    return out


def _parse_v4(payload) -> list:
    out = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        engine = str(entry.get("engine") or "")
        default_file = entry.get("fileName") or ""
        for v in entry.get("violations") or []:
            try:
                sev = _CA4_SEVERITY.get(int(v.get("severity", 2)), "Medium")
            except (TypeError, ValueError):
                sev = "Medium"
            category = v.get("category") or ""
            out.append(Violation(
                rule=str(v.get("ruleName") or ""),
                engine=engine,
                message=str(v.get("message") or "").strip(),
                # Graph Engine rows name a sink file rather than the entry's file.
                file=str(v.get("sinkFileName") or v.get("sourceFileName")
                         or default_file or ""),
                line=str(v.get("sinkLine") or v.get("line") or ""),
                severity=sev,
                tags=(str(category),) if category else (),
                url=str(v.get("url") or ""),
            ))
    return out


def _sarif_uri(location) -> str:
    phys = (location or {}).get("physicalLocation") or {}
    uri = ((phys.get("artifactLocation") or {}).get("uri") or "")
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    return uri


def _parse_sarif(payload) -> list:
    out = []
    for run in payload.get("runs") or []:
        driver = ((run.get("tool") or {}).get("driver") or {})
        engine = str(driver.get("name") or "")
        rules = driver.get("rules") or []
        for res in run.get("results") or []:
            rule_id = res.get("ruleId")
            rule_meta = {}
            idx = res.get("ruleIndex")
            if isinstance(idx, int) and 0 <= idx < len(rules):
                rule_meta = rules[idx] or {}
                rule_id = rule_id or rule_meta.get("id")
            level = str(res.get("level") or
                        ((rule_meta.get("defaultConfiguration") or {}).get("level"))
                        or "warning").lower()
            props = rule_meta.get("properties") or {}
            tags = list(props.get("tags") or [])
            if props.get("category"):
                tags.append(str(props["category"]))
            locations = res.get("locations") or []
            first = locations[0] if locations else {}
            region = ((first.get("physicalLocation") or {}).get("region") or {})
            out.append(Violation(
                rule=str(rule_id or ""),
                engine=engine,
                message=str((res.get("message") or {}).get("text") or "").strip(),
                file=_sarif_uri(first),
                line=str(region.get("startLine") or ""),
                severity=_SARIF_LEVEL.get(level, "Medium"),
                tags=tuple(str(t) for t in tags),
                url=str((rule_meta.get("helpUri") or "")),
            ))
    return out


def parse_code_analyzer(payload) -> tuple:
    """(violations, format_name) from an already-decoded Code Analyzer payload.

    Raises ValueError on a shape we do not recognise — the callers below turn
    that into a "not ingested, and here is why" result rather than an exception,
    but a caller parsing a file by hand should see the failure.
    """
    if isinstance(payload, dict) and "result" in payload and "status" in payload:
        return parse_code_analyzer(payload["result"])   # `sf ... --json` envelope
    if isinstance(payload, dict) and "runs" in payload:
        return _parse_sarif(payload), "SARIF"
    if isinstance(payload, dict) and "violations" in payload:
        return _parse_v5(payload), "Code Analyzer v5 JSON"
    if isinstance(payload, list):
        return _parse_v4(payload), "Code Analyzer v4 JSON"
    raise ValueError("unrecognised Code Analyzer payload — expected v4 JSON "
                     "(array), v5 JSON ({'violations': [...]}) or SARIF")


def violations_to_findings(violations) -> tuple:
    """(findings, unmapped_count).

    Violations of the same rule in the same file collapse into ONE finding
    carrying every line number. Code Analyzer reports one row per occurrence;
    forty AvoidSoqlInLoops rows in one class is one fix and must be one ticket,
    or the ingestion re-creates exactly the four-thousand-ticket dump the §4.6
    gate exists to prevent.
    """
    groups, order, unmapped = {}, [], 0
    for v in violations:
        mapped = _ca_dimension(v)
        if not mapped:
            unmapped += 1
            continue
        key = (_basename(v.file), v.rule)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((v, mapped))

    out = []
    for key in order:
        component, rule = key
        members = groups[key]
        dim, rule_id, defect = members[0][1]
        vs = [m[0] for m in members]
        severity = _worst([v.severity for v in vs], _SEV_RANK, "Low")
        lines = [v.line for v in vs if v.line]
        first = vs[0]
        engine = first.engine or "code analyzer"
        message = first.message or rule
        if len(message) > 160:
            message = message[:157] + "..."
        occurrences = ("" if len(vs) == 1
                       else f" ({len(vs)} occurrences)")
        detail_bits = [b for b in [first.file, "line(s) " + ", ".join(lines) if lines else ""]
                       if b]
        out.append(_finding(
            rule_id, dim, severity,
            # A parser and a data-flow graph, not a regex over brace-matched
            # text. Confidence is the tool's strongest claim, not ours.
            "High",
            component,
            f"{engine} rule {rule}: {message}{occurrences}",
            detail=" ".join(detail_bits),
            source=SOURCE_CODE_ANALYZER,
            defect_key=defect,
            tool_rule=f"{engine}/{rule}" if engine else rule,
            component_type=_component_type_for(component),
            reference=first.url,
        ))
    return out, unmapped


# ------------------------------------------------------------- invocation

def _has_code_analyzer(plugins) -> bool:
    """True only for an INSTALLED code-analyzer plugin.

    `sf plugins --json` lists just-in-time plugins next to installed ones, and
    the only thing separating them is `"type": "jit"`. A JIT entry means "the
    CLI would download this if you invoked the command" — a multi-minute install
    plus a JDK requirement, triggered in the middle of somebody's scan — so it
    counts as absent. (Checking `sf code-analyzer --help` is worse still: help
    renders fine on a CLI that has never installed the plugin.)
    """
    for plugin in plugins if isinstance(plugins, list) else []:
        entry = plugin or {}
        name = str(entry.get("name") or "")
        if "code-analyzer" in name and str(entry.get("type") or "") != "jit":
            return True
    return False


def code_analyzer_installed(timeout: int = 30) -> bool:
    """Is the `code-analyzer` plugin actually installed on this machine?"""
    try:
        proc = subprocess.run(["sf", "plugins", "--json"],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return False
        return _has_code_analyzer(json.loads(proc.stdout or "[]"))
    except Exception:                        # noqa: BLE001 - see module docstring
        return False


def _run_code_analyzer(workspace, timeout: int = CODE_ANALYZER_TIMEOUT) -> tuple:
    """(payload, error). Runs the plugin and reads its results file.

    Every failure mode — plugin gone, no JDK, timeout, unparseable output —
    comes back as an error string. A third-party CLI must never be able to end
    an OrgIQ scan.
    """
    try:
        # The results file is scratch: it is parsed here and the findings are
        # what survive, so it goes in a temp dir that cleans itself up rather
        # than littering the caller's workspace with a second artefact.
        with tempfile.TemporaryDirectory(prefix="orgiq-code-analyzer-") as tmpdir:
            out_file = os.path.join(tmpdir, "results.json")
            cmd = ["sf", "code-analyzer", "run", "--workspace", str(workspace),
                   "--output-file", out_file]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if not os.path.exists(out_file):
                reason = (proc.stderr or proc.stdout or "").strip().splitlines()
                return None, ("`sf code-analyzer run` produced no results file"
                              + (f" — {reason[-1][:200]}" if reason else ""))
            with open(out_file, encoding="utf-8") as fh:
                return json.load(fh), ""
    except subprocess.TimeoutExpired:
        return None, f"`sf code-analyzer run` exceeded {timeout}s and was abandoned"
    except FileNotFoundError:
        return None, "the `sf` CLI is not on PATH"
    except Exception as exc:                 # noqa: BLE001
        return None, f"`sf code-analyzer run` failed: {str(exc)[:200]}"


def code_analyzer_findings(results_file=None, workspace=None, invoke: bool = False,
                           runner=None, timeout: int = CODE_ANALYZER_TIMEOUT) -> ToolResult:
    """Ingest Code Analyzer output.

    `results_file` — a file the caller already has (CI artefact, manual run).
    Preferred, because it needs no plugin and no JDK.
    `invoke` — additionally allowed to run `sf code-analyzer run` over
    `workspace`, but only when the plugin is genuinely installed.
    `runner` — test seam: a callable(workspace, timeout) -> (payload, error).
    """
    res = ToolResult(tool=SOURCE_CODE_ANALYZER)
    payload, origin = None, ""

    if results_file:
        path = Path(results_file)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            origin = str(path)
        except OSError:
            res.detail = (f"no results file at {path} — Code Analyzer was not "
                          f"ingested and none of its signal is assumed")
            return res
        except ValueError as exc:
            res.detail = (f"{path} is not readable as JSON or SARIF "
                          f"({str(exc)[:120]}) — nothing ingested")
            return res
    elif invoke:
        run = runner or (_run_code_analyzer if code_analyzer_installed() else None)
        if run is None:
            res.detail = ("the `code-analyzer` plugin is not installed, so no "
                          "static analysis ran; OrgIQ's own D5 loop heuristics "
                          "are all that covered this ground")
            return res
        payload, err = run(workspace or ".", timeout)
        if err or payload is None:
            res.detail = (err or "the run produced no output") + " — nothing ingested"
            return res
        origin = f"`sf code-analyzer run --workspace {workspace or '.'}`"
    else:
        res.detail = ("no results file supplied and invocation was not requested "
                      "— Code Analyzer contributed nothing to this scan")
        return res

    try:
        violations, fmt = parse_code_analyzer(payload)
    except ValueError as exc:
        res.detail = f"{str(exc)[:180]} — nothing ingested"
        return res

    findings, unmapped = violations_to_findings(violations)
    res.ran = True
    res.findings = findings
    res.ingested = len(findings)
    res.unmapped = unmapped
    res.detail = (f"{len(findings)} finding(s) from {len(violations)} violation(s) "
                  f"in {fmt} ({origin})")
    if unmapped:
        res.detail += (f"; {unmapped} violation(s) matched no OrgIQ dimension and "
                       f"were left out rather than filed under the nearest one")
    return res


# ========================================================== Health Check
#
# The org's own answer to "how far is this org from Salesforce's security
# baseline". Read, never computed: SecurityHealthCheckRisks is a Tooling API
# object, one row per setting that misses the baseline, and SecurityHealthCheck
# carries the single percentage score Setup displays.

_HC_SEVERITY = {"HIGH_RISK": "High", "MEDIUM_RISK": "Medium", "LOW_RISK": "Low"}

_HC_RISKS_SOQL = (
    "SELECT DurableId, RiskType, Setting, SettingGroup, SettingRiskCategory, "
    "OrgValue, StandardValue FROM SecurityHealthCheckRisks"
)
_HC_SCORE_SOQL = "SELECT DurableId, Score FROM SecurityHealthCheck"


class SfQueryError(Exception):
    """A `sf data query` that did not come back with records."""


def _sf_query(soql: str, org: str, tooling: bool = True,
              timeout: int = SF_TIMEOUT) -> list:
    """Run one SOQL query through the `sf` CLI and return its records.

    The CLI holds the org's credentials; nothing here reads, prints or stores a
    token, and the org is addressed by alias only.
    """
    cmd = ["sf", "data", "query", "--query", soql, "--json",
           "--target-org", org]
    if tooling:
        cmd.append("--use-tooling-api")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SfQueryError(f"the query exceeded {timeout}s")
    except FileNotFoundError:
        raise SfQueryError("the `sf` CLI is not on PATH")
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        raise SfQueryError("the CLI returned output that is not JSON")
    if proc.returncode != 0 or payload.get("status"):
        msg = str(payload.get("message") or "the query failed").strip()
        raise SfQueryError(" ".join(msg.split())[:200])
    return (payload.get("result") or {}).get("records") or []


def health_check_findings(org=None, runner=None, timeout: int = SF_TIMEOUT) -> ToolResult:
    """Ingest Security Health Check risks from a live org.

    `runner` is the test seam: a callable(soql) -> records, standing in for
    `sf data query --use-tooling-api`.

    Emits one D4 finding per setting that misses the baseline, carrying the
    setting, the org's value, Salesforce's standard value, and the org's overall
    Health Check score. Settings that MEET the standard produce nothing — a scan
    reports defects, not an inventory.

    The org's overall score is deliberately NOT a finding of its own: it is the
    aggregate of exactly these risks, so scoring it too would count the same
    defect twice. It rides on `ToolResult.score` and in each finding's evidence.
    """
    res = ToolResult(tool=SOURCE_HEALTH_CHECK)
    if not org and runner is None:
        res.detail = ("no org alias supplied, so Health Check was not read; "
                      "OrgIQ has no view of this org's security posture")
        return res

    query = runner or (lambda soql: _sf_query(soql, org, timeout=timeout))

    try:
        risks = query(_HC_RISKS_SOQL)
    except SfQueryError as exc:
        res.detail = (f"SecurityHealthCheckRisks could not be read ({exc}) — no "
                      f"security-posture signal was collected and none is assumed")
        return res
    except Exception as exc:                 # noqa: BLE001
        res.detail = (f"SecurityHealthCheckRisks could not be read "
                      f"({str(exc)[:160]}) — nothing ingested")
        return res

    score = ""
    try:
        rows = query(_HC_SCORE_SOQL)
        if rows:
            score = str(rows[0].get("Score") or "")
    except Exception:                        # noqa: BLE001
        score = ""                           # the risks are still worth having

    findings, skipped = [], 0
    for row in risks:
        risk_type = str(row.get("RiskType") or row.get("SettingRiskCategory") or "")
        severity = _HC_SEVERITY.get(risk_type.upper())
        if not severity:
            skipped += 1                     # MEETS_STANDARD / INFORMATIONAL
            continue
        durable = str(row.get("DurableId") or row.get("Setting") or "unknown")
        setting = str(row.get("Setting") or durable)
        org_value = str(row.get("OrgValue") or "")
        standard = str(row.get("StandardValue") or "")
        evidence = (f"{setting} — org value {org_value!r}, Salesforce baseline "
                    f"{standard!r}")
        if score:
            evidence += f"; org Health Check score {score}%"
        findings.append(_finding(
            "D4.HEALTH_CHECK_RISK", "D4", severity,
            "High",                          # the org's own reading of itself
            durable, evidence,
            detail=f"group={row.get('SettingGroup') or ''} risk={risk_type}",
            source=SOURCE_HEALTH_CHECK,
            defect_key="healthcheck:" + durable.lower(),
            tool_rule=durable,
            component_type="Security Setting",
        ))

    res.ran = True
    res.findings = findings
    res.ingested = len(findings)
    res.score = score
    res.detail = (f"{len(findings)} setting(s) below the Salesforce baseline"
                  + (f", org score {score}%" if score else ", score unavailable")
                  + (f"; {skipped} setting(s) already meet the standard"
                     if skipped else ""))
    return res


# ============================================================== Optimizer
#
# Salesforce exposes NO API for Optimizer results. This is not an omission in
# this module: the Optimizer app renders its findings inside Setup (older
# releases emailed a PDF), and there is no supported object, no Tooling entity
# and no documented export contract to read. Anyone claiming to "call the
# Optimizer API" is claiming something that does not exist.
#
# So this adapter reads a file the operator exported or assembled by hand, in a
# documented shape, and does nothing at all when there is no file. It is never
# invoked, and its absence is reported rather than papered over.

# Category keyword -> (dimension, rule id, defect key, component type).
# `unreferenced-field` is shared with OrgIQ's D1.UNREFERENCED_FIELD on purpose:
# Optimizer sees every report, layout and dependency in the org, OrgIQ sees the
# committed report XML and a textual scan of Apex. Same defect, better witness —
# the merge below keeps Optimizer's.
_OPTIMIZER_MAP = (
    (("unused custom field", "unused field", "fields not used", "custom field usage"),
     ("D1", "D1.OPTIMIZER_UNUSED_FIELD", "unreferenced-field", "CustomField")),
    (("permission", "profile"),
     ("D4", "D4.OPTIMIZER_PERMISSION_RISK", "", "PermissionSet")),
)

_OPTIMIZER_DEFAULT_SEVERITY = "Medium"


def _optimizer_rows(path: Path) -> list:
    """Rows from a JSON or CSV export, as lower-cased-key dicts."""
    text = path.read_text(encoding="utf-8")
    rows = []
    if path.suffix.lower() == ".json" or text.lstrip().startswith(("{", "[")):
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("findings") or payload.get("results") or []
        rows = [r for r in payload if isinstance(r, dict)]
    else:
        rows = list(csv.DictReader(text.splitlines()))
    return [{str(k or "").strip().lower(): v for k, v in row.items()} for row in rows]


def optimizer_findings(export_file=None) -> ToolResult:
    """Ingest an exported Optimizer result set, if the operator supplied one.

    THERE IS NO OPTIMIZER API. Salesforce publishes Optimizer findings in the
    Optimizer app in Setup and nowhere else; nothing here can fetch them, and
    this adapter does not pretend otherwise — with no `export_file` it is a
    no-op that says so.

    Expected file shape (JSON array, or CSV with a header row) per finding:

        category    what Optimizer grouped it under, e.g. "Unused Custom Fields"
        component   the API name it is about, e.g. "Account.Legacy_Code__c"
        severity    optional — Critical / High / Medium / Low
        description optional — Optimizer's own wording

    Rows whose category maps onto no OrgIQ dimension are counted and reported,
    never re-filed under a dimension that happens to be nearby.
    """
    res = ToolResult(tool=SOURCE_OPTIMIZER)
    if not export_file:
        res.detail = ("no export supplied. Salesforce exposes no Optimizer API — "
                      "its findings live in the Optimizer app in Setup — so "
                      "OrgIQ ingests it only from a file, and nothing from "
                      "Optimizer is assumed in this scan")
        return res

    path = Path(export_file)
    try:
        rows = _optimizer_rows(path)
    except OSError:
        res.detail = f"no export file at {path} — nothing ingested"
        return res
    except ValueError as exc:
        res.detail = f"{path} could not be parsed ({str(exc)[:120]}) — nothing ingested"
        return res

    findings, unmapped = [], 0
    for row in rows:
        category = str(row.get("category") or row.get("finding") or "").strip()
        mapped = None
        for needles, target in _OPTIMIZER_MAP:
            if any(n in category.lower() for n in needles):
                mapped = target
                break
        if not mapped:
            unmapped += 1
            continue
        dim, rule_id, defect, ctype = mapped
        component = str(row.get("component") or row.get("api name")
                        or row.get("name") or "unknown").strip()
        severity = str(row.get("severity") or "").strip().title()
        if severity not in _SEV_RANK:
            severity = _OPTIMIZER_DEFAULT_SEVERITY
        description = str(row.get("description") or row.get("message")
                          or category).strip()
        findings.append(_finding(
            rule_id, dim, severity,
            # Optimizer computes from the live org, with the whole dependency
            # picture OrgIQ does not have in source mode.
            "High",
            component, f"Optimizer: {description}"[:300],
            detail=f"category={category}",
            source=SOURCE_OPTIMIZER,
            defect_key=defect or ("optimizer:" + category.lower()),
            tool_rule=category,
            component_type=ctype,
        ))

    res.ran = True
    res.findings = findings
    res.ingested = len(findings)
    res.unmapped = unmapped
    res.detail = f"{len(findings)} finding(s) ingested from {path}"
    if unmapped:
        res.detail += (f"; {unmapped} row(s) in categories OrgIQ does not model "
                       f"were reported, not re-filed")
    return res


# ========================================================== Deduplication
#
# Two engines describing one defect must produce one record.
#
# The merge key is (component, defect) — never the rule id, because the whole
# point is that D5.DML_IN_LOOP and pmd/AvoidDmlStatementsInLoops are two names
# for one thing. Native rule ids get their defect key from the table below;
# ingested findings carry theirs from the adapter; anything unmapped falls back
# to a key unique to its own rule, so unrelated findings can never collapse.
#
# The surviving record is the most authoritative one (_AUTHORITY), and it:
#   * keeps the winner's rule id, evidence, source and remediation — the ticket
#     must be actionable in the tool that can actually clear it;
#   * takes the WORST severity in the group, so a merge can never quietly
#     downgrade a defect;
#   * takes the BEST confidence in the group, because two independent engines
#     agreeing is genuinely stronger evidence than either alone. This can lift a
#     finding through the §4.6 backlog gate, which is the correct outcome: a
#     Low-confidence heuristic that a parser confirms is no longer a guess;
#   * records the folded findings in `corroborated_by`, and says so in its
#     evidence, so nothing disappears silently.

NATIVE_DEFECT_KEYS = {
    "D5.DML_IN_LOOP": "dml-in-loop",
    "D5.SOQL_IN_LOOP": "soql-in-loop",
    "D3.APEX_NO_TESTS": "apex-test-quality",
    "D1.UNREFERENCED_FIELD": "unreferenced-field",
}

# Component suffixes that name the same artefact ("BillingService.cls" from Code
# Analyzer, "BillingService" from a native trigger finding).
_COMPONENT_EXT = re.compile(r"\.(cls|trigger|apex|page|cmp|component|js|html)$", re.I)


def defect_key(finding) -> str:
    """Identity of the defect, independent of the engine that spotted it.

    Three cases, in order:

      * an ingested finding carries its own key, set by the adapter;
      * a native rule listed in NATIVE_DEFECT_KEYS gets the shared key, which is
        the whole point — that is where cross-engine merging happens, at the
        granularity both engines and the resulting ticket work at ("this class
        does DML in a loop");
      * everything else keys on its own rule id, plus `detail` for the rules
        where detail is IDENTITY rather than state. Two semantic-duplicate
        clusters on one object both render as "Obj [2 fields]" and are told
        apart only by their member list; without this they merge into one and a
        real finding disappears. `backlog` hashes detail into the external id
        for exactly this set of rules, and the two must stay in step.
    """
    explicit = getattr(finding, "defect_key", "")
    if explicit:
        return explicit
    shared = NATIVE_DEFECT_KEYS.get(finding.rule_id)
    if shared:
        return shared
    if finding.rule_id in backlog._IDENTITY_DETAIL_RULES and finding.detail:
        return f"{finding.rule_id}|{finding.detail}"
    return finding.rule_id


def component_key(finding) -> str:
    """Identity of the component, normalised across the shapes the engines use.

    Aggregate components ("Account [12 fields]") reduce to the object; file
    components lose their extension. Everything lower-cases, because Code
    Analyzer echoes the filesystem and the metadata does not.
    """
    comp = (finding.component or "").split(" [", 1)[0].strip()
    return _COMPONENT_EXT.sub("", comp).lower()


@dataclass
class Merge:
    """One fold, for the record — printed in reports and asserted on in tests."""
    component: str
    defect: str
    kept: str
    folded: tuple


def _rank(finding) -> tuple:
    return (_AUTHORITY.get(source_of(finding), 0),
            _SEV_RANK.get(finding.severity, 0),
            _CONF_RANK.get(finding.confidence, 0))


def _label(finding) -> str:
    return f"{source_of(finding)} {finding.rule_id}"


def merge_findings(findings) -> tuple:
    """(merged, merges). Keeps one finding per (component, defect).

    Mutates the surviving findings (severity, confidence, evidence,
    `corroborated_by`) and returns them in first-seen order, so a caller's
    native ordering survives. Run once, before scoring and before the backlog:
    running it twice would append the corroboration note twice.
    """
    groups, order = {}, []
    for f in findings:
        key = (component_key(f), defect_key(f))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)

    merged, merges = [], []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        winner = max(group, key=_rank)
        losers = [f for f in group if f is not winner]

        winner.severity = _worst([f.severity for f in group], _SEV_RANK, winner.severity)
        winner.confidence = _worst([f.confidence for f in group], _CONF_RANK,
                                   winner.confidence)
        notes = []
        for f in losers:
            label = _label(f)
            if label not in notes:
                notes.append(label)
        winner.evidence = f"{winner.evidence}; corroborated by {', '.join(notes)}"
        winner.corroborated_by = list(getattr(winner, "corroborated_by", [])) + notes
        merged.append(winner)
        merges.append(Merge(component=winner.component, defect=key[1],
                            kept=_label(winner), folded=tuple(notes)))
    return merged, merges


# ----------------------------------------------------------------- scoring

# Findings that are recorded and ticketed but must not move a dimension score.
# Health Check risks are org-wide security settings; D4 measures what an agent's
# permission set can reach. Scoring them would silently turn D4 into the
# security scan PRD §2.3 lists as a non-goal — and they would swamp it, since a
# stock org has more baseline gaps than it has agent permission problems.
UNSCORED_RULES = frozenset({"D4.HEALTH_CHECK_RISK"})


def scoreable(findings) -> list:
    """The subset of findings a caller should hand to the dimension scorer.

    Everything else still belongs in the report, in the backlog and in the
    Salesforce records — it is excluded from the arithmetic, not from view.
    """
    return [f for f in findings if f.rule_id not in UNSCORED_RULES]


# ------------------------------------------------------------- collection

def collect(code_analyzer_results=None, org=None, optimizer_export=None,
            workspace=None, run_code_analyzer: bool = False) -> ExternalScan:
    """Run every adapter that has an input, and record why the others did not.

    Nothing here raises: the worst case is an ExternalScan whose every result
    has `ran=False` and a sentence explaining what was not collected.
    """
    return ExternalScan(results=[
        code_analyzer_findings(results_file=code_analyzer_results,
                               workspace=workspace, invoke=run_code_analyzer),
        health_check_findings(org=org),
        optimizer_findings(export_file=optimizer_export),
    ])


# ------------------------------------------------------------------- CLI

def _print_report(scan: ExternalScan, merges=None):
    print("# Free-tool ingestion\n")
    for r in scan.results:
        state = "ingested" if r.ran else "not collected"
        print(f"- **{r.tool}** [{state}] — {r.detail}")
    findings = scan.findings
    print(f"\n{len(findings)} finding(s) ingested.\n")
    if findings:
        print("| Source | Rule | Dimension | Severity | Component | Evidence |")
        print("|---|---|---|---|---|---|")
        for f in findings:
            print(f"| {source_of(f)} | {f.rule_id} | {f.dimension} | {f.severity} "
                  f"| `{f.component}` | {f.evidence[:110]} |")
    for m in (merges or []):
        print(f"\nMerged: kept {m.kept} on `{m.component}` "
              f"({m.defect}); folded {', '.join(m.folded)}")


def main():
    ap = argparse.ArgumentParser(
        description="Ingest Salesforce's free tools (Code Analyzer, Security "
                    "Health Check, Optimizer) as OrgIQ findings")
    ap.add_argument("--org", default=None,
                    help="org alias for the Security Health Check query "
                         "(read-only; uses the `sf` CLI's own credentials)")
    ap.add_argument("--code-analyzer-results", default=None,
                    help="a Code Analyzer results file (v4 JSON, v5 JSON or SARIF)")
    ap.add_argument("--run-code-analyzer", action="store_true",
                    help="also run `sf code-analyzer run` when the plugin is "
                         "installed; skipped silently when it is not")
    ap.add_argument("--workspace", default=".",
                    help="workspace for --run-code-analyzer")
    ap.add_argument("--optimizer-export", default=None,
                    help="an exported Optimizer result file (JSON or CSV); "
                         "Salesforce exposes no API for these")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the ingested findings as JSON to this path")
    a = ap.parse_args()

    scan = collect(code_analyzer_results=a.code_analyzer_results, org=a.org,
                   optimizer_export=a.optimizer_export, workspace=a.workspace,
                   run_code_analyzer=a.run_code_analyzer)
    _print_report(scan)

    if a.json_out:
        rows = [{
            "rule_id": f.rule_id, "dimension": f.dimension, "severity": f.severity,
            "confidence": f.confidence, "component": f.component,
            "evidence": f.evidence, "detail": f.detail, "source": source_of(f),
            "tool_rule": getattr(f, "tool_rule", ""),
            "reference": getattr(f, "reference", ""),
        } for f in scan.findings]
        Path(a.json_out).write_text(json.dumps(
            {"findings": rows,
             "tools": [{"tool": r.tool, "ran": r.ran, "detail": r.detail}
                       for r in scan.results]}, indent=2), encoding="utf-8")
        print(f"\nwrote {a.json_out}")
    # Always exit 0. A tool that was unavailable is a reported result, not a
    # failed run — a non-zero exit would push a CI caller into treating a
    # missing signal as an error and, eventually, into ignoring it.
    return 0


if __name__ == "__main__":
    sys.exit(main())
