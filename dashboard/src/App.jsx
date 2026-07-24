import { useEffect, useState } from 'react'
import { loadPortfolio } from './lib/data.js'
import {
  isConfigured, beginLogin, handleRedirect, getStoredToken, loadLivePortfolio, logout,
} from './lib/live.js'
import PortfolioView from './views/PortfolioView.jsx'
import OrgDetail from './views/OrgDetail.jsx'

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
  const [source, setSource] = useState('demo')   // 'demo' | 'live'
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const hash = useHashRoute()

  useEffect(() => {
    (async () => {
      let tok = null
      try {
        tok = await handleRedirect()             // just came back from Salesforce?
      } catch (e) {
        setNotice(`Live sign-in failed: ${e.message}. Showing demo data.`)
      }
      tok = tok || getStoredToken()
      if (tok) {
        try {
          setData(await loadLivePortfolio(tok))
          setSource('live')
          return
        } catch (e) {
          logout()
          setNotice(`Couldn't load live data (${e.message}). Showing demo data.`)
        }
      }
      try {
        setData(await loadPortfolio())
        setSource('demo')
      } catch (e) {
        setError(e.message)
      }
    })()
  }, [])

  const disconnect = () => { logout(); window.location.reload() }

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
        <div className="topbar__actions">
          {source === 'live' ? (
            <>
              <span className="pill pill--live">● Live · {data ? data.scans.length : '…'} orgs</span>
              <button className="btn btn--sm" onClick={disconnect}>Disconnect</button>
            </>
          ) : (
            <>
              <span className="pill pill--demo">Demo · {data ? data.scans.length : '…'} orgs</span>
              {isConfigured() && (
                <button className="btn btn--sm" onClick={() => beginLogin()}>
                  Connect Salesforce
                </button>
              )}
            </>
          )}
        </div>
      </header>

      {notice && <div className="banner">{notice}</div>}
      {error && <div className="state state--error">Failed to load portfolio: {error}</div>}
      {!error && !data && <div className="state">Loading portfolio…</div>}

      {data && !selected && <PortfolioView data={data} />}
      {data && selected && <OrgDetail data={data} scan={selected} />}

      <footer className="foot">
        <span>
          OrgIQ is a readiness assessment, not a certification. Findings are observed
          in each org, not asserted as typical; D2–D5 rules and effort points are
          provisional. {source === 'demo' && 'Demo data is bundled from the OrgIQ org.'}
        </span>
        <a href="https://github.com/singhaditya21/SFORGIQ" target="_blank" rel="noreferrer">
          github.com/singhaditya21/SFORGIQ
        </a>
      </footer>
    </div>
  )
}
