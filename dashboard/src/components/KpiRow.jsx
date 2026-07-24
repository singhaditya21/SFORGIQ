// Metric tiles. The ones that map to a filter are clickable — clicking "not
// ready" or "critical" filters the whole dashboard to those records.

// 2.2 stays "2.2", 18 does not become "18.0" — and 9.96 reads "10", not the
// "10.0" a naive threshold on the raw value produces.
function pct(n) {
  const s = n >= 10 ? String(Math.round(n)) : n.toFixed(1)
  return s.endsWith('.0') ? s.slice(0, -2) : s
}

export default function KpiRow({ stats, grounding, filter, onFilter }) {
  // A portfolio whose scans all predate the grounding fields shows an em dash
  // rather than a zero that would read as "measured, and clean".
  const hasGrounding = !!grounding && grounding.current > 0

  const items = [
    { n: stats.orgCount, label: 'orgs scanned' },
    { n: stats.avgComposite, label: 'avg readiness', suffix: '/100' },
    { n: stats.totalComponents.toLocaleString(), label: 'components' },
    { n: stats.notReady, label: 'not ready', tone: 'bad', on: ['band', 'Not Ready'] },
    { n: stats.foundational, label: 'foundational', on: ['band', 'Foundational Work Required'] },
    { n: stats.conditional, label: 'conditional', on: ['band', 'Conditionally Ready'] },
    { n: stats.ready, label: 'ready', tone: 'good', on: ['band', 'Ready'] },
    { n: stats.totalFindings.toLocaleString(), label: 'findings' },
    { n: stats.critical.toLocaleString(), label: 'critical', tone: 'bad', on: ['severity', 'Critical'] },
    { n: stats.high.toLocaleString(), label: 'high', on: ['severity', 'High'] },
    { n: stats.totalBacklog.toLocaleString(), label: 'backlog items' },
    { n: stats.totalEffort.toLocaleString(), label: 'effort pts', prov: true },
    // Grounding economics. Both figures are deterministic estimates over
    // normalised text, not a tokenizer's count and not a bill — hence "est.".
    // Double-width: a 5-digit token count with a unit, and these labels, do not
    // fit a single column, and forcing them to wrap stretched the whole row.
    {
      n: hasGrounding ? grounding.current.toLocaleString() : '—',
      suffix: hasGrounding ? ' tok' : '',
      label: 'grounding payload',
      est: true,
      wide: true,
    },
    {
      n: hasGrounding ? pct(grounding.removablePct) : '—',
      suffix: hasGrounding ? '%' : '',
      label: 'removable payload',
      est: true,
      wide: true,
    },
  ]
  return (
    <div className="kpis">
      {items.map((it) => {
        const active = it.on && filter[it.on[0]] === it.on[1]
        const cls = `kpi ${it.tone ? `kpi--${it.tone}` : ''} ${it.wide ? 'kpi--wide' : ''} `
          + `${it.on ? 'kpi--click' : ''} ${active ? 'kpi--on' : ''}`
        const body = (
          <>
            <div className="kpi__n">
              {it.n}{it.suffix && <span className="kpi__suffix">{it.suffix}</span>}
            </div>
            <div className="kpi__label">
              {it.label}
              {it.prov && <span className="kpi__prov"> · prov.</span>}
              {it.est && <span className="kpi__prov"> · est.</span>}
            </div>
          </>
        )
        return it.on ? (
          <button key={it.label} className={cls} onClick={() => onFilter(it.on[0], it.on[1])}
                  title={`Filter to ${it.label}`}>{body}</button>
        ) : (
          <div key={it.label} className={cls}>{body}</div>
        )
      })}
    </div>
  )
}
