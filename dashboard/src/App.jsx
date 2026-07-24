import { useEffect, useState } from 'react'
import { loadPortfolio } from './lib/data.js'
import PortfolioView from './views/PortfolioView.jsx'
import OrgDetail from './views/OrgDetail.jsx'

// Tiny hash router so the app works on static GitHub Pages hosting.
// #/                     -> portfolio overview
// #/org/<externalScanId> -> org detail
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || '#/')
  useEffect(() => {
    const on = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash
}

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const hash = useHashRoute()

  useEffect(() => {
    loadPortfolio().then(setData).catch((e) => setError(e.message))
  }, [])

  const orgMatch = hash.match(/^#\/org\/(.+)$/)
  const selected = orgMatch
    ? data?.scans.find((s) => s.scan.externalId === decodeURIComponent(orgMatch[1]))
    : null

  return (
    <div className="app">
      <header className="topbar">
        <a className="topbar__brand" href="#/">
          <span className="topbar__logo" aria-hidden>🛰️</span>
          <div>
            <div className="topbar__title">OrgIQ</div>
            <div className="topbar__subtitle">Agentforce Readiness Analyzer</div>
          </div>
        </a>
        <span className="pill pill--demo" title="Data bundled from the OrgIQ Salesforce org">
          Demo · {data ? data.scans.length : '…'} orgs from Salesforce
        </span>
      </header>

      {error && <div className="state state--error">Failed to load portfolio: {error}</div>}
      {!error && !data && <div className="state">Loading portfolio…</div>}

      {data && !selected && <PortfolioView data={data} />}
      {data && selected && <OrgDetail data={data} scan={selected} />}

      <footer className="foot">
        <span>
          OrgIQ is a readiness assessment, not a certification. Only D1 (Grounding
          Quality) is assessed today; findings are observed in each org, not asserted
          as typical; effort points are provisional.
        </span>
        <a href="https://github.com/singhaditya21/SFORGIQ" target="_blank" rel="noreferrer">
          github.com/singhaditya21/SFORGIQ
        </a>
      </footer>
    </div>
  )
}
