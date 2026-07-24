import { useState } from 'react'
import { bandKey } from '../lib/data.js'

// Readiness (x) vs remediation effort (y) scatter — where should a practice
// spend? Left = low readiness (needs work); high = lots of effort. Click a dot
// to open that org.
export default function Quadrant({ rows, activeBand }) {
  const [hover, setHover] = useState(null)
  const W = 640, H = 380
  const padL = 46, padR = 18, padT = 18, padB = 42
  const maxEffort = Math.max(10, ...rows.map((r) => r.effort))
  const x = (c) => padL + (c / 100) * (W - padL - padR)
  const y = (e) => (H - padB) - (e / maxEffort) * (H - padT - padB)

  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }

  return (
    <svg className="quad" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Readiness versus remediation effort by org">
      {/* band boundary guides */}
      {[40, 60, 80].map((b) => (
        <line key={b} x1={x(b)} x2={x(b)} y1={padT} y2={H - padB} className="quad__guide" />
      ))}
      {[40, 60, 80].map((b) => (
        <text key={`t${b}`} x={x(b)} y={H - padB + 14} className="quad__gtick">{b}</text>
      ))}
      {/* axes */}
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} className="quad__axis" />
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} className="quad__axis" />
      <text x={(padL + W - padR) / 2} y={H - 6} className="quad__label">Readiness score →</text>
      <text x={-((padT + H - padB) / 2)} y={13} transform="rotate(-90)" className="quad__label">
        Remediation effort (pts) →
      </text>

      {rows.map((r) => (
        <circle
          key={r.externalId}
          cx={x(r.composite)} cy={y(r.effort)}
          r={hover === r.externalId ? 8 : 6}
          className={`quad__dot quad__dot--${bandKey(r.band)} ${activeBand && activeBand !== r.band ? 'quad__dot--dim' : ''}`}
          onMouseEnter={() => setHover(r.externalId)}
          onMouseLeave={() => setHover(null)}
          onClick={() => go(r.externalId)}
        >
          <title>{r.name}</title>
        </circle>
      ))}

      {hover && (() => {
        const r = rows.find((o) => o.externalId === hover)
        const tw = 190, th = 58
        const tx = Math.min(Math.max(x(r.composite) + 10, padL), W - tw - 4)
        const ty = Math.min(Math.max(y(r.effort) - th - 8, 2), H - th - 2)
        return (
          <g className="quad__tip" pointerEvents="none">
            <rect x={tx} y={ty} width={tw} height={th} rx="7" />
            <text x={tx + 10} y={ty + 20} className="quad__tipname">{r.name}</text>
            <text x={tx + 10} y={ty + 38} className="quad__tipmeta">
              {r.composite}/100 · {r.band}
            </text>
            <text x={tx + 10} y={ty + 51} className="quad__tipmeta">
              {r.findings} findings · {r.effort} pts
            </text>
          </g>
        )
      })()}
    </svg>
  )
}
