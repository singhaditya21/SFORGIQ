// Pentagon radar of the five dimension scores — one glance at where an org is
// strong or weak. Unassessed dimensions plot at the centre.
const ORDER = ['D1', 'D2', 'D3', 'D4', 'D5']

export default function DimensionRadar({ dimensions }) {
  const W = 260, H = 240, cx = 130, cy = 120, R = 82
  const byCode = Object.fromEntries(dimensions.map((d) => [d.code, d]))
  const dims = ORDER.map((c) => byCode[c]).filter(Boolean)
  const n = dims.length || 5
  const ang = (i) => (-90 + (360 / n) * i) * (Math.PI / 180)
  const pt = (i, rad) => [cx + Math.cos(ang(i)) * rad, cy + Math.sin(ang(i)) * rad]

  const ring = (frac) =>
    dims.map((_, i) => pt(i, R * frac).join(',')).join(' ')
  const dataPts = dims.map((d, i) => pt(i, R * ((d.score ?? 0) / 100)))
  const dataPoly = dataPts.map((p) => p.join(',')).join(' ')

  return (
    <svg className="radar" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Dimension scores radar">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} className="radar__ring" points={ring(f)} />
      ))}
      {dims.map((_, i) => {
        const [x, y] = pt(i, R)
        return <line key={i} className="radar__axis" x1={cx} y1={cy} x2={x} y2={y} />
      })}
      <polygon className="radar__area" points={dataPoly} />
      {dims.map((d, i) => {
        const [x, y] = dataPts[i]
        const [lx, ly] = pt(i, R + 16)
        return (
          <g key={d.code}>
            <circle className="radar__dot" cx={x} cy={y} r="3.5" />
            <text className="radar__axislabel" x={lx} y={ly}
                  textAnchor={Math.abs(lx - cx) < 6 ? 'middle' : lx < cx ? 'end' : 'start'}>
              {d.code}
            </text>
            <text className="radar__axisscore" x={lx} y={ly + 12}
                  textAnchor={Math.abs(lx - cx) < 6 ? 'middle' : lx < cx ? 'end' : 'start'}>
              {d.score == null ? '—' : d.score}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
