// Who does the work.
//
// The tool's stated output is a backlog, and a backlog nobody owns is a list.
// This is the split that decides whether it can be handed over at all: four
// teams with their own queues, or one person holding a thousand tickets.
//
// Points, not ticket counts, drive the ordering and the bar — 300 description
// edits and 30 trigger rewrites are not the same amount of work, and sorting by
// count would put the cheapest queue first.
export default function OwnerSplit({ rows }) {
  if (!rows.length) return <div className="drift__none">No routed work.</div>
  const max = Math.max(...rows.map((r) => r.points), 1)
  return (
    <div className="owners">
      {rows.map((r) => (
        <div key={r.role} className="owners__row">
          <span className="owners__role">{r.role}</span>
          <span className="owners__bar">
            <span className="owners__fill" style={{ width: `${(r.points / max) * 100}%` }} />
          </span>
          <span className="owners__nums">
            <b>{r.points.toLocaleString()}</b> pts
            <span className="owners__sub"> · {r.tickets.toLocaleString()} tickets</span>
            {r.critical > 0 && <span className="tag tag--critical">{r.critical} critical</span>}
          </span>
        </div>
      ))}
    </div>
  )
}
