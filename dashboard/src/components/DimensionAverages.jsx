// Portfolio-wide average score per dimension — where the whole book of orgs is
// strong or weak. Blue bars, darker = the metric, on a light track.
export default function DimensionAverages({ averages }) {
  return (
    <div className="dimavg">
      {averages.map((d) => (
        <div key={d.code} className="dimavg__row">
          <span className="dimavg__code">{d.code}</span>
          <span className="dimavg__name">{d.name}</span>
          <div className="dimavg__bar">
            <div className="dimavg__fill" style={{ width: `${d.avg}%` }} />
          </div>
          <span className="dimavg__val">{d.avg}</span>
        </div>
      ))}
    </div>
  )
}
