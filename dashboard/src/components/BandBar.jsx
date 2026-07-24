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
      <div className="bandbar__legend">
        {breakdown.map((b) => (
          <button key={b.band}
                  className={`bandbar__key ${active === b.band ? 'bandbar__key--on' : ''}`}
                  onClick={() => toggle(b.band)}>
            <span className={`dot dot--band-${bandKey(b.band)}`} />
            {BAND_META[b.band].short} <b>{b.count}</b>
          </button>
        ))}
        {active && <button className="bandbar__clear" onClick={() => onSelect(null)}>clear ✕</button>}
      </div>
    </div>
  )
}
