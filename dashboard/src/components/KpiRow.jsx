export default function KpiRow({ stats }) {
  const items = [
    { n: stats.orgCount, label: 'orgs scanned' },
    { n: stats.avgComposite, label: 'avg readiness', suffix: '/100' },
    { n: stats.notReady, label: 'not ready', tone: 'bad' },
    { n: stats.ready, label: 'ready', tone: 'good' },
    { n: stats.totalFindings.toLocaleString(), label: 'findings' },
    { n: stats.totalBacklog.toLocaleString(), label: 'backlog items' },
    { n: stats.totalEffort.toLocaleString(), label: 'effort pts', prov: true },
  ]
  return (
    <div className="kpis">
      {items.map((it) => (
        <div key={it.label} className={`kpi ${it.tone ? `kpi--${it.tone}` : ''}`}>
          <div className="kpi__n">
            {it.n}{it.suffix && <span className="kpi__suffix">{it.suffix}</span>}
          </div>
          <div className="kpi__label">
            {it.label}{it.prov && <span className="kpi__prov"> · prov.</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
