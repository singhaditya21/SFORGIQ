// PKCE helpers (RFC 7636) using the Web Crypto API.

function base64url(bytes) {
  const s = btoa(String.fromCharCode(...new Uint8Array(bytes)))
  return s.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function randomString(len = 64) {
  const a = new Uint8Array(len)
  crypto.getRandomValues(a)
  return base64url(a).slice(0, len)
}

export async function challengeFromVerifier(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64url(digest)
}
