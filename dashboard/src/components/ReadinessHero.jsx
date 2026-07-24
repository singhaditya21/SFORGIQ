import { BAND_META } from '../lib/data.js'

// SVG donut gauge for the composite score, coloured by readiness band.
function Gauge({ score, bandKey }) {
  const r = 74
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, score)) / 100
  return (
    <svg className="gauge" viewBox="0 0 180 180" role="img"
         aria-label={`Composite score ${score} of 100`}>
      <circle className="gauge__track" cx="90" cy="90" r={r} />
      <circle
        className={`gauge__value gauge__value--${bandKey}`}
        cx="90" cy="90" r={r}
        strokeDasharray={c}
        strokeDashoffset={c * (1 - pct)}
        transform="rotate(-90 90 90)"
      />
      <text className="gauge__score" x="90" y="86">{score}</text>
      <text className="gauge__outof" x="90" y="112">of 100</text>
    </svg>
  )
}

export default function ReadinessHero({ scan }) {
  const meta = BAND_META[scan.readinessBand] ?? { key: 'not-ready', blurb: '' }
  return (
    <section className="card hero">
      <div className="hero__gauge">
        <Gauge score={scan.compositeScore} bandKey={meta.key} />
      </div>
      <div className="hero__body">
        <div className="hero__label">Composite readiness</div>
        <div className={`hero__band hero__band--${meta.key}`}>{scan.readinessBand}</div>
        <p className="hero__blurb">{meta.blurb}</p>
        {scan.gateApplied && (
          <div className="hero__gate">
            ⚠ Gate applied — {scan.gateReason}
          </div>
        )}
        <div className="hero__note">
          Composite is scored over assessed dimensions only. Partially- or
          un-assessed dimensions are excluded and shown separately.
        </div>
      </div>
    </section>
  )
}
