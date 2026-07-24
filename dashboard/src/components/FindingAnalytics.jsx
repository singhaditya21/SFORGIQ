// Cross-portfolio finding mix — what kinds of problems dominate, and how they
// split by severity. Every bar and every severity chip is a filter.
export default function FindingAnalytics({ breakdown, rule, severity, onRule, onSeverity }) {
  const max = Math.max(1, ...breakdown.rules.map((r) => r.count))
  return (
    <div className="analytics">
      <div className="analytics__rules">
        {breakdown.rules.map((r) => (
          <button key={r.ruleId}
                  className={`arule ${rule === r.ruleId ? 'arule--on' : ''}`}
                  onClick={() => onRule(r.ruleId)}
                  title={`Filter to ${r.label} findings`}>
            <span className="arule__top">
              <span className="arule__name">{r.label}</span>
              <span className="arule__count">{r.count.toLocaleString()}</span>
            </span>
            <span className="arule__bar">
              <span className="arule__fill" style={{ width: `${(r.count / max) * 100}%` }} />
            </span>
          </button>
        ))}
      </div>
      <div className="analytics__sev">
        {breakdown.severities.map((s) => (
          <button key={s.severity}
                  className={`sevrow ${severity === s.severity ? 'sevrow--on' : ''}`}
                  onClick={() => onSeverity(s.severity)}
                  title={`Filter to ${s.severity} findings`}>
            <span className={`dot dot--${s.severity.toLowerCase()}`} />
            <span className="sevrow__name">{s.severity}</span>
            <span className="sevrow__count">{s.count.toLocaleString()}</span>
          </button>
        ))}
        <span className="analytics__total">{breakdown.total.toLocaleString()} findings across the portfolio</span>
      </div>
    </div>
  )
}
