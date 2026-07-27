// Which objects carry the most grounding debt in this org.
//
// `active` and `onSelect` are optional so the component still renders in a
// context that has nowhere to drill to — but where they are passed, the row is
// a real button. A div with `cursor: pointer` and no handler is worse than a
// plain one: it promises something and then does nothing.
export default function ComponentRollup({ rollup, active = null, onSelect = null }) {
  const max = Math.max(1, ...rollup.map((r) => r.count))
  const Row = onSelect ? 'button' : 'div'
  return (
    <div className="rollup">
      {rollup.map((r) => (
        <Row key={r.object}
             className={`rollrow${onSelect ? ' rollrow--click' : ''}`
               + (active === r.object ? ' is-active' : '')}
             {...(onSelect ? { onClick: () => onSelect(r.object), type: 'button' } : {})}>
          <span className="rollrow__name"><code>{r.object}</code></span>
          <div className="rollrow__bar">
            <div className="rollrow__fill" style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
          <span className="rollrow__count">{r.count}</span>
        </Row>
      ))}
    </div>
  )
}
