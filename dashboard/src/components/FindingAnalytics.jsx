// Cross-portfolio finding mix — what kinds of problems dominate, and how they
// split by severity. This is where a practice would build remediation playbooks.
export default function FindingAnalytics({ breakdown }) {
  const max = Math.max(1, ...breakdown.rules.map((r) => r.count))
  return (
    <div className="analytics">
      <div className="analytics__rules">
        {breakdown.rules.map((r) => (
          <div key={r.ruleId} className="arule">
            <div className="arule__top">
              <span className="arule__name">{r.label}</span>
              <span className="arule__count">{r.count.toLocaleString()}</span>
            </div>
            <div className="arule__bar">
              <div className="arule__fill" style={{ width: `${(r.count / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="analytics__sev">
        {breakdown.severities.map((s) => (
          <div key={s.severity} className="sevrow">
            <span className={`dot dot--${s.severity.toLowerCase()}`} />
            <span className="sevrow__name">{s.severity}</span>
            <span className="sevrow__count">{s.count.toLocaleString()}</span>
          </div>
        ))}
        <div className="analytics__total">{breakdown.total.toLocaleString()} findings across the portfolio</div>
      </div>
    </div>
  )
}
