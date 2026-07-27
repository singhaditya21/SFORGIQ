import { splitName, bandKey } from '../lib/data.js'

// Composite-score trend across a family of scans (e.g. Helios Q1..Q4) — the
// remediation burn-down that turns a one-off audit into a fundable programme.
export default function TrendChart({ family, currentId, onSelect = null }) {
  const W = 620, H = 200, padL = 34, padR = 16, padT = 20, padB = 34
  const pts = family.members.map((m, i) => ({
    id: m.scan.externalId,
    label: splitName(m.scan.targetOrg).label || m.scan.name,
    score: m.scan.compositeScore,
    band: m.scan.readinessBand,
    i,
  }))
  const n = pts.length
  const x = (i) => padL + (n === 1 ? 0.5 : i / (n - 1)) * (W - padL - padR)
  const y = (s) => (H - padB) - (s / 100) * (H - padT - padB)
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.i)},${y(p.score)}`).join(' ')

  return (
    <svg className="trend" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`Composite score trend for ${family.base}`}>
      {[0, 40, 60, 80, 100].map((g) => (
        <g key={g}>
          <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)} className="trend__grid" />
          <text x={padL - 6} y={y(g) + 3} className="trend__ytick">{g}</text>
        </g>
      ))}
      <path d={path} className="trend__line" />
      {pts.map((p) => (
        <g key={p.id} className={onSelect && p.id !== currentId ? 'trend__pt' : ''}
           {...(onSelect && p.id !== currentId
             ? { onClick: () => onSelect(p.id), role: 'button', tabIndex: 0,
                 'aria-label': `Open the ${p.label} scan, scored ${p.score}` }
             : {})}>
          {/* A generous invisible target: a 5px dot is not something anyone can
              reliably hit, and a burn-down whose points cannot be opened is a
              picture rather than a way into the scan behind it. */}
          {onSelect && p.id !== currentId && (
            <circle cx={x(p.i)} cy={y(p.score)} r={16} className="trend__hit" />
          )}
          <circle cx={x(p.i)} cy={y(p.score)}
                  r={p.id === currentId ? 7 : 5}
                  className={`trend__dot trend__dot--${bandKey(p.band)} ${p.id === currentId ? 'trend__dot--current' : ''}`} />
          <text x={x(p.i)} y={y(p.score) - 12} className="trend__val">{p.score}</text>
          <text x={x(p.i)} y={H - 12} className="trend__xtick">{p.label}</text>
        </g>
      ))}
    </svg>
  )
}
