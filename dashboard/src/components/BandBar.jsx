import { bandKey, BAND_META } from '../lib/data.js'

// Segmented bar of how many orgs sit in each readiness band. Click a segment to
// filter the orgs below to that band (click again to clear).
export default function BandBar({ breakdown, active, onSelect }) {
  const total = breakdown.reduce((s, b) => s + b.count, 0) || 1
  const toggle = (band) => onSelect(active === band ? null : band)
  return (
    <div className="bandbar">
      <div className="bandbar__track">
        {breakdown.map((b) => b.count > 0 && (
          <button
            key={b.band}
            className={`bandbar__seg bandbar__seg--${bandKey(b.band)} ${active && active !== b.band ? 'bandbar__seg--dim' : ''}`}
            style={{ width: `${(b.count / total) * 100}%` }}
            title={`${b.band}: ${b.count} — click to filter`}
            onClick={() => toggle(b.band)}
          >
            {b.count}
          </button>
        ))}
      </div>
      {/* What each band costs, not just how many orgs are in it. */}
      <table className="bandtab">
        <thead>
          <tr><th>Band</th><th className="c-num">Orgs</th><th className="c-num">Avg</th>
            <th className="c-num">Findings</th><th className="c-num">Effort</th></tr>
        </thead>
        <tbody>
          {breakdown.map((b) => (
            <tr key={b.band}
                className={`bandtab__row ${active === b.band ? 'bandtab__row--on' : ''}`}
                onClick={() => toggle(b.band)} title={`Filter to ${b.band}`}>
              <td>
                <span className={`dot dot--band-${bandKey(b.band)}`} />
                {BAND_META[b.band].short}
              </td>
              <td className="c-num"><b>{b.count}</b></td>
              <td className="c-num">{b.avgScore ?? '—'}</td>
              <td className="c-num">{b.findings.toLocaleString()}</td>
              <td className="c-num">{b.effort.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {active && (
        <button className="bandbar__clear" onClick={() => onSelect(null)}>clear filter ✕</button>
      )}
    </div>
  )
}
