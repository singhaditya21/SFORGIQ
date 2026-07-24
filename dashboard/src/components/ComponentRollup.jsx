// Which objects carry the most grounding debt in this org.
export default function ComponentRollup({ rollup }) {
  const max = Math.max(1, ...rollup.map((r) => r.count))
  return (
    <div className="rollup">
      {rollup.map((r) => (
        <div key={r.object} className="rollrow">
          <span className="rollrow__name"><code>{r.object}</code></span>
          <div className="rollrow__bar">
            <div className="rollrow__fill" style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
          <span className="rollrow__count">{r.count}</span>
        </div>
      ))}
    </div>
  )
}
