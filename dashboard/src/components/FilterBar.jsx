import { BAND_META, ruleLabel } from '../lib/data.js'

const LABELS = {
  band: (v) => `Band: ${BAND_META[v]?.short ?? v}`,
  dimension: (v) => `Dimension: ${v}`,
  rule: (v) => `Rule: ${ruleLabel(v)}`,
  severity: (v) => `Severity: ${v}`,
}

// Whatever you clicked, shown back to you and removable. Without this a
// cross-filtering dashboard just feels broken.
export default function FilterBar({ filter, onClear, onDrop, matchCount, orgCount }) {
  const active = Object.entries(filter).filter(([, v]) => v)
  if (!active.length) return null
  return (
    <div className="filterbar">
      <span className="filterbar__label">Filtered</span>
      {active.map(([k, v]) => (
        <button key={k} className="filterbar__chip" onClick={() => onDrop(k)}
                title="Remove this filter">
          {LABELS[k](v)} <span className="filterbar__x">✕</span>
        </button>
      ))}
      <span className="filterbar__count">
        {orgCount} org{orgCount === 1 ? '' : 's'}
        {matchCount != null && ` · ${matchCount.toLocaleString()} findings`}
      </span>
      <button className="filterbar__clear" onClick={onClear}>Clear all</button>
    </div>
  )
}
