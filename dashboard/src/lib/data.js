// Data loading + domain metadata + derivations for the OrgIQ dashboard.

// Demo mode reads the bundled portfolio exported from the OrgIQ Salesforce org.
// (A future live mode would swap this for an OAuth'd Salesforce REST query.)
export async function loadPortfolio() {
  const res = await fetch(`${import.meta.env.BASE_URL}portfolio.json`)
  if (!res.ok) throw new Error(`could not load portfolio (${res.status})`)
  return res.json()
}

// Readiness bands (PRD §4.3).
export const BAND_ORDER = [
  'Not Ready',
  'Foundational Work Required',
  'Conditionally Ready',
  'Ready',
]
export const BAND_META = {
  'Not Ready': { key: 'not-ready', short: 'Not Ready', blurb: 'Agent deployment will fail. Foundational remediation required first.' },
  'Foundational Work Required': { key: 'foundational', short: 'Foundational', blurb: 'Narrow, low-risk agents feasible. Broad deployment is not.' },
  'Conditionally Ready': { key: 'conditional', short: 'Conditional', blurb: 'Deploy with named mitigations and a monitoring plan.' },
  Ready: { key: 'ready', short: 'Ready', blurb: 'No structural blockers identified.' },
}
export function bandKey(band) { return BAND_META[band]?.key ?? 'not-ready' }

export const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low']

// Rule display metadata.
//
// `label` is dashboard-only. `epic` and `acceptance` are a MIRROR of
// scanner/backlog.py `_PLAYBOOK` — that file is the source of truth, this is a
// cache for findings exported before the org carried Epic__c /
// Acceptance_Criteria__c. When a rule is added or its playbook wording changes
// in backlog.py, update it here too, verbatim: a silent drift here shows up as
// two different epic names for the same rule in the same backlog.
export const RULE_META = {
  'D1.MISSING_DESCRIPTION': {
    label: 'Missing description',
    epic: 'Add missing field descriptions',
    acceptance: 'Field has a non-empty description that states its business meaning '
      + '(not just a restatement of the label). Re-scan reports no '
      + 'D1.MISSING_DESCRIPTION for this field.',
  },
  'D1.LOW_INFO_DESCRIPTION': {
    label: 'Label-restating description',
    epic: 'Replace label-restating field descriptions',
    acceptance: 'Description carries information beyond the label. Re-scan reports no '
      + 'D1.LOW_INFO_DESCRIPTION for this field.',
  },
  'D1.CRYPTIC_API_NAME': {
    label: 'Cryptic field name',
    epic: 'Clarify cryptic field names',
    acceptance: 'Field is unambiguous to a reader with no tribal knowledge — via a clear '
      + 'description and/or a readable API name. Re-scan reports no '
      + 'D1.CRYPTIC_API_NAME for this field.',
  },
  'D1.NUMBERED_FAMILY': {
    label: 'Numbered field family',
    epic: 'Resolve numbered field families',
    acceptance: 'Either the group is modelled as a related list, or each member carries a '
      + 'distinct, disambiguating description. Re-scan reports no '
      + 'D1.NUMBERED_FAMILY for this object, or a smaller family.',
  },
  'D1.SEMANTIC_DUPLICATE': {
    label: 'Duplicate field',
    epic: 'Consolidate duplicate fields',
    acceptance: 'One canonical field remains; duplicates are deprecated with data and '
      + 'references migrated. Re-scan reports no D1.SEMANTIC_DUPLICATE for this cluster.',
  },
  'D1.UNREFERENCED_FIELD': {
    label: 'Unreferenced field',
    epic: 'Retire unreferenced fields',
    acceptance: "Field is deleted, or retained with a documented reason and hidden from the "
      + "agent's layouts and permissions. Absence of references was verified against "
      + 'integrations and managed packages, not just the committed report metadata. '
      + 'Re-scan reports no D1.UNREFERENCED_FIELD for this field.',
  },
  'D2.LOW_FILL_RATE': {
    label: 'Low fill rate',
    epic: 'Backfill under-populated fields',
    acceptance: 'Fill rate on the field exceeds the grounding threshold; re-scan clears the finding.',
  },
  'D2.STALE_DATA': {
    label: 'Stale data',
    epic: 'Refresh stale data',
    acceptance: 'Stale-record ratio falls below threshold; re-scan clears the finding.',
  },
  'D2.DUPLICATE_RECORDS': {
    label: 'Duplicate records',
    epic: 'De-duplicate records',
    acceptance: 'Duplicate rate below threshold; re-scan clears the finding.',
  },
  'D3.NO_SAFE_ACTIONS': {
    label: 'No safe actions',
    epic: 'Build a safe action surface',
    acceptance: 'At least one bulk-safe invocable action exists per intended task; re-scan clears the finding.',
  },
  'D3.UNDOCUMENTED_ACTION': {
    label: 'Undocumented action',
    epic: 'Document invocable actions',
    acceptance: 'Action carries a planner-usable description; re-scan clears the finding.',
  },
  'D3.APEX_NO_TESTS': {
    label: 'Untested Apex',
    epic: 'Cover agent-invoked Apex with tests',
    acceptance: 'Class has meaningful test coverage; re-scan clears the finding.',
  },
  'D3.INACTIVE_ACTION': {
    label: 'Inactive flow',
    epic: 'Activate or retire dormant flows',
    acceptance: 'No Draft/Obsolete flow is exposed as an agent action; re-scan clears it.',
  },
  'D4.MODIFY_ALL_DATA': {
    label: 'Modify All Data',
    epic: 'Remove Modify All Data from the agent',
    acceptance: 'Agent permission set no longer grants Modify All Data; re-scan clears the finding.',
  },
  'D4.VIEW_ALL_DATA': {
    label: 'View All Data',
    epic: 'Remove View All Data from the agent',
    acceptance: 'Agent permission set no longer grants View All Data; re-scan clears the finding.',
  },
  'D4.WIDE_OBJECT_ACCESS': {
    label: 'Over-broad access',
    epic: 'Tighten over-broad object access',
    acceptance: 'Object access matches task scope; re-scan clears the finding.',
  },
  'D4.DELETE_GRANTED': {
    label: 'Delete granted',
    epic: 'Remove unnecessary delete rights',
    acceptance: 'Delete is granted only where a task requires it; re-scan clears it.',
  },
  'D5.DML_IN_LOOP': {
    label: 'DML in loop',
    epic: 'Bulkify automation',
    acceptance: 'No DML in loops on the automation path; bulk tests pass; re-scan clears the finding.',
  },
  'D5.SOQL_IN_LOOP': {
    label: 'SOQL in loop',
    epic: 'Bulkify automation',
    acceptance: 'No SOQL inside loops on the automation path; re-scan clears it.',
  },
  'D5.MULTIPLE_TRIGGERS': {
    label: 'Multiple triggers',
    epic: 'Consolidate triggers per object',
    acceptance: 'One trigger per object with defined order; re-scan clears the finding.',
  },
  'D5.NO_RECURSION_GUARD': {
    label: 'No recursion guard',
    epic: 'Add recursion guards',
    acceptance: 'Automation is recursion-safe; re-scan clears the finding.',
  },
  'D5.TRIGGER_AND_FLOW': {
    label: 'Trigger + flow collision',
    epic: 'Resolve trigger/flow ordering collisions',
    acceptance: 'One deterministic automation path per object; re-scan clears it.',
  },
}
// Mirrors backlog._UNKNOWN — a rule the dashboard build predates still needs an
// epic and an acceptance line, or its ticket imports without either.
const UNKNOWN_RULE = {
  epic: 'Grounding quality findings',
  acceptance: 'Re-scan no longer reports this finding for the component.',
}
export function ruleLabel(ruleId) { return RULE_META[ruleId]?.label ?? ruleId }

// ---- per-org rollups ----------------------------------------------------
export function orgEffort(findings) {
  return findings.filter((f) => f.emitsToBacklog).reduce((s, f) => s + (f.effortPoints || 0), 0)
}
export function orgBacklogCount(findings) {
  return findings.filter((f) => f.emitsToBacklog).length
}
export function topIssue(findings) {
  const c = {}
  for (const f of findings) c[f.ruleId] = (c[f.ruleId] || 0) + 1
  const best = Object.entries(c).sort((a, b) => b[1] - a[1])[0]
  return best ? ruleLabel(best[0]) : '—'
}

// Flatten to a per-org summary row used by the portfolio table + quadrant.
export function orgRows(scans) {
  return scans.map((s) => ({
    externalId: s.scan.externalId,
    name: s.scan.targetOrg,
    mode: s.scan.scanMode,
    composite: s.scan.compositeScore,
    band: s.scan.readinessBand,
    findings: s.findings.length,
    backlog: orgBacklogCount(s.findings),
    effort: orgEffort(s.findings),
    topIssue: topIssue(s.findings),
  }))
}

// ---- portfolio aggregates ----------------------------------------------
export function portfolioStats(scans) {
  const rows = orgRows(scans)
  const n = rows.length || 1
  const allFindings = scans.flatMap((s) => s.findings)
  const sev = severityCounts(allFindings)
  const totalFindings = rows.reduce((s, r) => s + r.findings, 0)
  const totalComponents = scans.reduce((s, x) => s + (x.scan.componentsScanned || 0), 0)
  return {
    orgCount: rows.length,
    avgComposite: Math.round(rows.reduce((s, r) => s + r.composite, 0) / n),
    notReady: rows.filter((r) => r.band === 'Not Ready').length,
    foundational: rows.filter((r) => r.band === 'Foundational Work Required').length,
    conditional: rows.filter((r) => r.band === 'Conditionally Ready').length,
    ready: rows.filter((r) => r.band === 'Ready').length,
    totalFindings,
    critical: sev.Critical,
    high: sev.High,
    avgFindings: Math.round(totalFindings / n),
    totalComponents,
    totalBacklog: rows.reduce((s, r) => s + r.backlog, 0),
    totalEffort: rows.reduce((s, r) => s + r.effort, 0),
    gated: scans.filter((s) => s.scan.gateApplied).length,
  }
}

// Every finding in the portfolio, tagged with the org it came from — the basis
// for cross-filtering (click a rule/dimension/severity anywhere, see the matches).
export function flattenFindings(scans) {
  const out = []
  for (const s of scans) {
    for (const f of s.findings) {
      out.push({ ...f, org: s.scan.targetOrg, orgId: s.scan.externalId })
    }
  }
  return out
}

export function applyFindingFilter(findings, filter) {
  return findings
    .filter((f) => !filter.dimension || f.dimension === filter.dimension)
    .filter((f) => !filter.rule || f.ruleId === filter.rule)
    .filter((f) => !filter.severity || f.severity === filter.severity)
}

export const EMPTY_FILTER = { band: null, dimension: null, rule: null, severity: null }
export function filterIsActive(f) {
  return !!(f.band || f.dimension || f.rule || f.severity)
}
export function findingFilterActive(f) {
  return !!(f.dimension || f.rule || f.severity)
}

// One row per org with its five dimension scores — feeds the heatmap.
export function heatmapRows(scans) {
  return scans
    .map((s) => {
      const dims = {}
      for (const d of s.dimensions) dims[d.code] = d.score
      return {
        externalId: s.scan.externalId,
        name: s.scan.targetOrg,
        composite: s.scan.compositeScore,
        band: s.scan.readinessBand,
        findings: s.findings.length,
        dims,
      }
    })
    .sort((a, b) => a.composite - b.composite)
}

// Average score per dimension across the orgs that assessed it.
export function dimensionAverages(scans) {
  const acc = {}
  for (const s of scans) {
    for (const d of s.dimensions) {
      if (d.score == null) continue
      const a = (acc[d.code] ||= { code: d.code, name: d.name, sum: 0, n: 0 })
      a.sum += d.score
      a.n += 1
    }
  }
  return Object.values(acc)
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((a) => ({ code: a.code, name: a.name, avg: Math.round(a.sum / a.n), orgs: a.n }))
}

export function bandBreakdown(scans) {
  const c = Object.fromEntries(BAND_ORDER.map((b) => [b, 0]))
  for (const s of scans) c[s.scan.readinessBand] = (c[s.scan.readinessBand] || 0) + 1
  return BAND_ORDER.map((band) => ({ band, count: c[band] }))
}

// Finding counts across the whole portfolio, by rule and by severity.
export function portfolioFindingBreakdown(scans) {
  const byRule = {}, bySev = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0]))
  let total = 0
  for (const s of scans) {
    for (const f of s.findings) {
      byRule[f.ruleId] = (byRule[f.ruleId] || 0) + 1
      bySev[f.severity] = (bySev[f.severity] || 0) + 1
      total += 1
    }
  }
  const rules = Object.entries(byRule)
    .map(([ruleId, count]) => ({ ruleId, label: ruleLabel(ruleId), count }))
    .sort((a, b) => b.count - a.count)
  const severities = SEVERITY_ORDER.filter((s) => bySev[s] > 0).map((s) => ({ severity: s, count: bySev[s] }))
  return { rules, severities, total }
}

// ---- org-detail derivations --------------------------------------------
export function severityCounts(findings) {
  const c = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0]))
  for (const f of findings) c[f.severity] = (c[f.severity] || 0) + 1
  return c
}

export function backlogSummary(findings) {
  const gated = findings.filter((f) => f.emitsToBacklog)
  const byEpic = {}
  for (const f of gated) {
    // The finding's own epic when the export carries one, so the summary and
    // the downloaded CSV never disagree about which epic a ticket belongs to.
    const epic = f.epic || RULE_META[f.ruleId]?.epic || f.ruleId
    if (!byEpic[epic]) byEpic[epic] = { epic, count: 0, effort: 0 }
    byEpic[epic].count += 1
    byEpic[epic].effort += f.effortPoints || 0
  }
  return {
    ticketCount: gated.length,
    observationCount: findings.length - gated.length,
    totalEffort: gated.reduce((s, f) => s + (f.effortPoints || 0), 0),
    epics: Object.values(byEpic).sort((a, b) => b.effort - a.effort),
  }
}

// Roll findings up to the object they sit on (component is "Obj.Field" or "Obj [N fields]").
export function objectOf(component) {
  return component.split('.')[0].split(' [')[0]
}
export function componentRollup(findings, limit = 8) {
  const by = {}
  for (const f of findings) {
    const o = objectOf(f.component)
    if (!by[o]) by[o] = { object: o, count: 0, effort: 0 }
    by[o].count += 1
    by[o].effort += f.emitsToBacklog ? (f.effortPoints || 0) : 0
  }
  return Object.values(by).sort((a, b) => b.count - a.count).slice(0, limit)
}

// ---- time-series families ----------------------------------------------
// "Helios Airlines · 2025-Q1" -> base "Helios Airlines", label "2025-Q1".
export function splitName(name) {
  const i = name.indexOf(' · ')
  return i === -1 ? { base: name, label: '' } : { base: name.slice(0, i), label: name.slice(i + 3) }
}
export function familyOf(scans, scan) {
  const base = splitName(scan.targetOrg).base
  const members = scans
    .filter((s) => splitName(s.scan.targetOrg).base === base)
    .sort((a, b) => splitName(a.scan.targetOrg).label.localeCompare(splitName(b.scan.targetOrg).label))
  return members.length > 1 ? { base, members } : null
}

// ---- backlog CSV -------------------------------------------------------
//
// This is the Jira import file a stakeholder downloads from the dashboard, so
// it has to BE the scanner's file, not a lookalike: same columns, same order,
// same header strings, same row shaping as scanner/backlog.py. Anything else
// and the demo hands out a spreadsheet that Jira's importer cannot map.
// Keep this block and backlog.py in lockstep.

// Verbatim from backlog.BACKLOG_COLUMNS.
const BACKLOG_COLUMNS = [
  'External ID',
  'Issue Type',
  'Epic Name',
  'Summary',
  'Priority',
  'Story Points (provisional)',
  'Labels',
  'Salesforce Component',
  'Component Type',
  'Rule ID',
  'Dimension',
  'Severity',
  'Confidence',
  'Rule Maturity',
  'Source',
  'Description',
]

// backlog._PRIORITY / _SEV_RANK / _CONF_RANK / FINDING_SOURCE.
const JIRA_PRIORITY = { Critical: 'Highest', High: 'High', Medium: 'Medium', Low: 'Low' }
const SEV_RANK = { Critical: 4, High: 3, Medium: 2, Low: 1 }
const CONF_RANK = { High: 3, Medium: 2, Low: 1 }
const DEFAULT_FINDING_SOURCE = 'OrgIQ'

// Python compares strings by code point; localeCompare does not, and the row
// order is part of matching the scanner's output.
function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0 }

function componentTypeOf(f) {
  // Prefer the stored value; fall back to backlog._component_type's rule
  // (aggregate findings render as "Object [N fields]").
  return f.componentType || (f.component.includes('[') ? 'CustomField group' : 'CustomField')
}

function backlogDescription(scan, f) {
  const meta = RULE_META[f.ruleId] ?? UNKNOWN_RULE
  // The exported finding carries the org's own epic/acceptance/source once the
  // scan has been loaded into Salesforce; RULE_META covers older exports.
  const acceptance = f.acceptanceCriteria || meta.acceptance
  return [
    `Rule: ${f.ruleId} (${f.dimension} — Grounding Quality)`,
    `Severity: ${f.severity}   Confidence: ${f.confidence}`,
    `Component: ${f.component}  [${componentTypeOf(f)}]`,
    '',
    // backlog.py emits a separate "Detail:" line; by the time a finding reaches
    // the dashboard its detail is already folded into evidence ("ev — detail"),
    // so there is nothing left to break out.
    `Evidence: ${f.evidence}`,
    '',
    'Remediation:',
    f.remediation || '',
    '',
    `Acceptance criteria: ${acceptance}`,
    '',
    'Blast radius: n/a (source mode — no dependency graph)',
    `Scan source: ${scan.targetOrg}`,
    `Finding source: ${f.source || DEFAULT_FINDING_SOURCE}`,
    'Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).',
  ].join('\n')
}

// Keyed by column name, then emitted in BACKLOG_COLUMNS order — the same
// DictWriter shape backlog.to_rows uses, so a column can never silently drift
// out of position the way a positional array lets it.
function backlogRow(scan, f) {
  const meta = RULE_META[f.ruleId] ?? UNKNOWN_RULE
  return {
    'External ID': f.externalId,
    'Issue Type': 'Task',
    'Epic Name': f.epic || meta.epic,
    Summary: `[${f.ruleId}] ${f.component}: ${f.evidence}`.slice(0, 200),
    Priority: JIRA_PRIORITY[f.severity] ?? 'Medium',
    'Story Points (provisional)': f.effortPoints,
    Labels: `OrgIQ ${f.dimension} ${f.ruleId.replace(/\./g, '_')}`,
    'Salesforce Component': f.component,
    'Component Type': componentTypeOf(f),
    'Rule ID': f.ruleId,
    Dimension: f.dimension,
    Severity: f.severity,
    Confidence: f.confidence,
    'Rule Maturity': f.ruleMaturity || 'experimental',
    Source: f.source || DEFAULT_FINDING_SOURCE,
    Description: backlogDescription(scan, f),
  }
}

// QUOTE_MINIMAL, matching Python's csv writer.
function csvCell(v) {
  const s = String(v ?? '')
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function backlogCsv(scan, findings) {
  const rows = findings
    // The §4.6 gate again, in case a caller hands us everything: an observation
    // that failed the gate must never arrive as a ticket.
    .filter((f) => f.emitsToBacklog)
    .sort((a, b) => (SEV_RANK[b.severity] ?? 0) - (SEV_RANK[a.severity] ?? 0)
      || (CONF_RANK[b.confidence] ?? 0) - (CONF_RANK[a.confidence] ?? 0)
      || cmp(a.ruleId, b.ruleId)
      || cmp(a.component, b.component))
    .map((f) => {
      const row = backlogRow(scan, f)
      return BACKLOG_COLUMNS.map((c) => csvCell(row[c])).join(',')
    })
  // CRLF-terminated rows, trailing terminator included (the Description cell
  // keeps its own bare newlines inside the quotes) — RFC 4180, and byte-for-byte
  // what Python's csv writer produces.
  return [BACKLOG_COLUMNS.join(','), ...rows].map((r) => `${r}\r\n`).join('')
}
export function downloadCsv(filename, text) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
