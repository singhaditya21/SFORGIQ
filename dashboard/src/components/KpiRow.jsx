// Metric tiles. The ones that map to a filter are clickable — clicking "not
// ready" or "critical" filters the whole dashboard to those records.
export default function KpiRow({ stats, filter, onFilter }) {
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
  ]
  return (
    <div className="kpis">
      {items.map((it) => {
        const active = it.on && filter[it.on[0]] === it.on[1]
        const cls = `kpi ${it.tone ? `kpi--${it.tone}` : ''} ${it.on ? 'kpi--click' : ''} ${active ? 'kpi--on' : ''}`
        const body = (
          <>
            <div className="kpi__n">
              {it.n}{it.suffix && <span className="kpi__suffix">{it.suffix}</span>}
            </div>
            <div className="kpi__label">
              {it.label}{it.prov && <span className="kpi__prov"> · prov.</span>}
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
