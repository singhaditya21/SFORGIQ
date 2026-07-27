import { BAND_META, ruleLabel } from '../lib/data.js'

const LABELS = {
  band: (v) => `Band: ${BAND_META[v]?.short ?? v}`,
  dimension: (v) => `Dimension: ${v}`,
  rule: (v) => `Rule: ${ruleLabel(v)}`,
  severity: (v) => `Severity: ${v}`,
  role: (v) => `Team: ${v}`,
}

// A filter key with no label here used to crash the whole page — `LABELS[k]`
// is undefined and it is called immediately. Falling back to the raw key shows
// something slightly ugly instead of a blank screen, which is the right way
// round for a bar whose only job is to make the current filter escapable.
const labelFor = (k, v) => (LABELS[k] ? LABELS[k](v) : `${k}: ${v}`)

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
          {labelFor(k, v)} <span className="filterbar__x">✕</span>
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
