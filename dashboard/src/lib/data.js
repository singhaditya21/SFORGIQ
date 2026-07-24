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

export const RULE_META = {
  'D1.MISSING_DESCRIPTION': { label: 'Missing description', epic: 'Add missing field descriptions' },
  'D1.LOW_INFO_DESCRIPTION': { label: 'Label-restating description', epic: 'Replace label-restating descriptions' },
  'D1.CRYPTIC_API_NAME': { label: 'Cryptic field name', epic: 'Clarify cryptic field names' },
  'D1.NUMBERED_FAMILY': { label: 'Numbered field family', epic: 'Resolve numbered field families' },
  'D1.SEMANTIC_DUPLICATE': { label: 'Duplicate field', epic: 'Consolidate duplicate fields' },
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
  return {
    orgCount: rows.length,
    avgComposite: Math.round(rows.reduce((s, r) => s + r.composite, 0) / n),
    notReady: rows.filter((r) => r.band === 'Not Ready').length,
    ready: rows.filter((r) => r.band === 'Ready').length,
    totalFindings: rows.reduce((s, r) => s + r.findings, 0),
    totalBacklog: rows.reduce((s, r) => s + r.backlog, 0),
    totalEffort: rows.reduce((s, r) => s + r.effort, 0),
  }
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
    const epic = RULE_META[f.ruleId]?.epic ?? f.ruleId
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

// ---- backlog CSV (client-side download; mirrors scanner/backlog.py columns) ----
function csvCell(v) {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
export function backlogCsv(scan, findings) {
  const cols = ['External ID', 'Rule', 'Severity', 'Confidence', 'Component',
    'Evidence', 'Effort (provisional)', 'Emits To Backlog', 'Remediation']
  const lines = [cols.join(',')]
  for (const f of findings) {
    lines.push([
      f.externalId, f.ruleId, f.severity, f.confidence, f.component,
      f.evidence, f.effortPoints, f.emitsToBacklog ? 'yes' : 'no', f.remediation,
    ].map(csvCell).join(','))
  }
  return lines.join('\n')
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
