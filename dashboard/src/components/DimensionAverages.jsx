// Portfolio-wide average score per dimension. Click a row to filter everything
// to that dimension's findings.
export default function DimensionAverages({ averages, dimension, onDimension }) {
  return (
    <div className="dimavg">
      {averages.map((d) => (
        <button
          key={d.code}
          className={`dimavg__row ${dimension === d.code ? 'dimavg__row--on' : ''}`}
          onClick={() => onDimension(d.code)}
          title={`Filter to ${d.code} findings`}
        >
          <span className="dimavg__code">{d.code}</span>
          <span className="dimavg__name">{d.name}</span>
          <span className="dimavg__bar">
            <span className="dimavg__fill" style={{ width: `${d.avg}%` }} />
          </span>
          <span className="dimavg__val">{d.avg}</span>
        </button>
      ))}
    </div>
  )
}
