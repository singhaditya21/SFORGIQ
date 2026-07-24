// Salesforce OAuth (PKCE public client) config for live mode.
//
// The client id is a PKCE *public* client id — it is not a secret and is safe
// to ship in the browser. Live mode only works from the registered callback
// origin (the GitHub Pages URL); on any other origin the redirect is rejected,
// which is expected. To point the dashboard at a different OrgIQ org, change
// clientId + loginUrl to that org's connected app and My Domain.
export const sfConfig = {
  clientId: '3MVG9HtWXcDGV.nE6MmJPx1cFe9KdsTFJBHm8ZeZdHVBuhj.BEI5.fKX6TBCrbk7MElL0bmiE6ov_iz7ABny5',
  loginUrl: 'https://orgfarm-6f6f46827b-dev-ed.develop.my.salesforce.com',
  apiVersion: 'v60.0',
}

export function redirectUri() {
  return window.location.origin + window.location.pathname
}
