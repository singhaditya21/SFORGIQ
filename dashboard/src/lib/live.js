// Live mode: OAuth 2.0 Authorization Code + PKCE against the OrgIQ Salesforce
// org, then read scans/findings via the REST query API. No backend — the token
// exchange happens in the browser, which is why the org needs this origin on
// its CORS allowlist.

import { sfConfig, redirectUri } from './sfConfig.js'
import { randomString, challengeFromVerifier } from './pkce.js'

const V = 'orgiq_pkce_verifier'
const S = 'orgiq_pkce_state'
const TOK = 'orgiq_sf_token'

export function isConfigured() {
  return !!sfConfig.clientId
}

export function getStoredToken() {
  try { return JSON.parse(sessionStorage.getItem(TOK) || 'null') } catch { return null }
}

export function logout() {
  sessionStorage.removeItem(TOK)
}

export async function beginLogin() {
  const verifier = randomString(96)
  const state = randomString(24)
  sessionStorage.setItem(V, verifier)
  sessionStorage.setItem(S, state)
  const challenge = await challengeFromVerifier(verifier)
  const p = new URLSearchParams({
    response_type: 'code',
    client_id: sfConfig.clientId,
    redirect_uri: redirectUri(),
    scope: 'api refresh_token openid',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  window.location.href = `${sfConfig.loginUrl}/services/oauth2/authorize?${p}`
}

function cleanUrl() {
  window.history.replaceState({}, '', window.location.origin + window.location.pathname + '#/')
}

// Call once on load: if we're back from Salesforce with ?code=, exchange it.
// Returns a token, or null if this isn't a redirect. Throws on OAuth error.
export async function handleRedirect() {
  const u = new URL(window.location.href)
  const err = u.searchParams.get('error')
  if (err) { cleanUrl(); throw new Error(u.searchParams.get('error_description') || err) }
  const code = u.searchParams.get('code')
  if (!code) return null
  if (u.searchParams.get('state') !== sessionStorage.getItem(S)) {
    cleanUrl(); throw new Error('OAuth state mismatch')
  }
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    client_id: sfConfig.clientId,
    redirect_uri: redirectUri(),
    code_verifier: sessionStorage.getItem(V) || '',
  })
  const res = await fetch(`${sfConfig.loginUrl}/services/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  cleanUrl()
  if (!res.ok) throw new Error(`token exchange failed (${res.status}) — check the org CORS allowlist`)
  const t = await res.json()
  const tok = { accessToken: t.access_token, instanceUrl: t.instance_url }
  sessionStorage.setItem(TOK, JSON.stringify(tok))
  return tok
}

async function soql(tok, q) {
  let url = `${tok.instanceUrl}/services/data/${sfConfig.apiVersion}/query?q=${encodeURIComponent(q)}`
  const rows = []
  while (url) {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${tok.accessToken}` } })
    if (res.status === 401) throw new Error('session expired — reconnect')
    if (!res.ok) throw new Error(`query failed (${res.status})`)
    const page = await res.json()
    rows.push(...page.records)
    url = page.done ? null : tok.instanceUrl + page.nextRecordsUrl
  }
  return rows
}

const dimCode = (n) => n.split(' ', 1)[0]
const dimShort = (n) => (n.includes(' ') ? n.slice(n.indexOf(' ') + 1) : n)

// Query the org and return the same shape as the bundled portfolio.json.
export async function loadLivePortfolio(tok) {
  const scans = await soql(tok,
    'SELECT Name,External_Scan_Id__c,Target_Org__c,Scan_Mode__c,Rubric_Version__c,' +
    'Composite_Score__c,Readiness_Band__c,Components_Scanned__c,Gate_Applied__c,' +
    'Gate_Reason__c,Scan_Timestamp__c FROM OrgIQ_Scan__c ORDER BY Composite_Score__c ASC')
  const dims = await soql(tok,
    'SELECT Scan__r.External_Scan_Id__c,Dimension__c,Score__c,Rule_Coverage__c,' +
    'In_Composite__c,Assessment_Status__c,Missing_Signals__c FROM OrgIQ_Dimension_Score__c')
  const finds = await soql(tok,
    'SELECT Scan__r.External_Scan_Id__c,External_Finding_Id__c,Rule_Id__c,Dimension__c,' +
    'Severity__c,Confidence__c,Component_Type__c,Component_Api_Name__c,Evidence__c,' +
    'Remediation__c,Effort_Points__c,Blast_Radius__c,Emits_To_Backlog__c,Rule_Maturity__c,' +
    'Status__c FROM OrgIQ_Finding__c')

  const dByScan = {}, fByScan = {}
  for (const d of dims) {
    const sid = d.Scan__r.External_Scan_Id__c;
    (dByScan[sid] ||= []).push({
      code: dimCode(d.Dimension__c), name: dimShort(d.Dimension__c), fullName: d.Dimension__c,
      score: d.Score__c, coverage: d.Rule_Coverage__c, inComposite: d.In_Composite__c,
      status: d.Assessment_Status__c, missingSignals: d.Missing_Signals__c || '',
    })
  }
  for (const f of finds) {
    const sid = f.Scan__r.External_Scan_Id__c;
    (fByScan[sid] ||= []).push({
      externalId: f.External_Finding_Id__c, ruleId: f.Rule_Id__c, dimension: f.Dimension__c,
      severity: f.Severity__c, confidence: f.Confidence__c, componentType: f.Component_Type__c,
      component: f.Component_Api_Name__c, evidence: f.Evidence__c || '',
      remediation: f.Remediation__c || '', effortPoints: f.Effort_Points__c,
      blastRadius: f.Blast_Radius__c, emitsToBacklog: f.Emits_To_Backlog__c,
      ruleMaturity: f.Rule_Maturity__c, status: f.Status__c,
    })
  }
  return {
    source: 'live',
    scans: scans.map((s) => {
      const sid = s.External_Scan_Id__c
      return {
        scan: {
          name: s.Name, externalId: sid, targetOrg: s.Target_Org__c, scanMode: s.Scan_Mode__c,
          rubricVersion: s.Rubric_Version__c, compositeScore: s.Composite_Score__c,
          readinessBand: s.Readiness_Band__c, componentsScanned: s.Components_Scanned__c,
          gateApplied: s.Gate_Applied__c, gateReason: s.Gate_Reason__c || '', timestamp: s.Scan_Timestamp__c,
        },
        dimensions: (dByScan[sid] || []).sort((a, b) => a.code.localeCompare(b.code)),
        findings: fByScan[sid] || [],
      }
    }),
  }
}
