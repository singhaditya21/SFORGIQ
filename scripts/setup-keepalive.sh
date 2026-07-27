#!/usr/bin/env bash
#
# One-time setup for the Salesforce keep-alive workflow.
#
#   bash scripts/setup-keepalive.sh            # uses org alias "orgiq"
#   bash scripts/setup-keepalive.sh myalias    # or a different alias
#
# It reads this machine's Salesforce auth and stores it as the GitHub Actions
# secret SFDX_AUTH_URL, so the weekly workflow can log in on its own. The token
# goes straight from your machine into GitHub's encrypted secret store — run
# this yourself; never paste the auth URL anywhere else.
#
# gh must be authenticated (run `gh auth login`, or prefix this command with
# `GH_TOKEN=<your-token> `).

set -euo pipefail
ORG="${1:-orgiq}"
REPO="singhaditya21/SFORGIQ"

command -v sf >/dev/null || { echo "Salesforce CLI (sf) not found."; exit 1; }
command -v gh >/dev/null || { echo "GitHub CLI (gh) not found — install with: brew install gh"; exit 1; }

echo "→ Obtaining a CI auth URL for org '$ORG'…"
AUTH_URL=$(sf org display --verbose --target-org "$ORG" --json 2>/dev/null \
  | python3 -c "import sys,json;print((json.load(sys.stdin)['result'].get('sfdxAuthUrl') or '').strip())" || true)

if [[ "${AUTH_URL:-}" != force://* ]]; then
  echo "  CLI didn't emit a standard auth URL — reconstructing it from the local auth file…"
  USERNAME=$(sf org display --target-org "$ORG" --json | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['username'])")
  AUTH_FILE="$HOME/.sfdx/$USERNAME.json"
  [ -f "$AUTH_FILE" ] || { echo "Auth file not found: $AUTH_FILE"; exit 1; }
  AUTH_URL=$(python3 - "$AUTH_FILE" <<'PY'
import sys, json
d = json.load(open(sys.argv[1]))
cid, sec, rt = d.get('clientId', ''), d.get('clientSecret', ''), d.get('refreshToken', '')
host = (d.get('instanceUrl') or '').replace('https://', '').replace('http://', '')
if not rt:
    sys.exit("no refresh token in the auth file — re-auth once with: sf org login web --alias " + "orgiq")
print(f"force://{cid}:{sec}:{rt}@{host}")
PY
)
fi

[[ "${AUTH_URL:-}" == force://* ]] || { echo "Could not obtain a valid auth URL."; exit 1; }

# Prove the token can actually do what the workflow will ask of it, BEFORE
# storing it. This script used to store whatever it found; a refresh token that
# had already expired went into the secret, and the only symptom was a workflow
# failing a week later with an error nobody was watching for. A local access
# token that still works is not evidence -- `sf` keeps using it until it
# expires, so the CLI looks healthy long after the refresh grant has died.
echo "-> Checking the refresh token still works..."
CHECK=$(python3 - "$AUTH_URL" <<'CHECKPY'
import sys, json, urllib.request, urllib.parse, urllib.error
rest = sys.argv[1][len("force://"):]
creds, host = rest.rsplit("@", 1)
token = creds.split("::", 1)[1] if "::" in creds else creds.split(":")[-1]
payload = urllib.parse.urlencode({"grant_type": "refresh_token",
                                  "client_id": "PlatformCLI",
                                  "refresh_token": token}).encode()
try:
    urllib.request.urlopen("https://%s/services/oauth2/token" % host, payload)
    print("OK")
except urllib.error.HTTPError as e:
    body = json.loads(e.read() or "{}")
    print("%s: %s" % (body.get("error", "?"), body.get("error_description", "")))
except Exception as exc:
    print("unreachable: %s" % exc)
CHECKPY
)

if [[ "$CHECK" != "OK" ]]; then
  cat <<MSG

x The refresh token cannot mint an access token: $CHECK

  Nothing was stored -- a dead token in the secret fails silently every Monday,
  which is exactly what happened last time. Salesforce will not re-issue a
  refresh token to a script, so the fix is one browser login, which only you
  can do:

      sf org login web --alias $ORG

  Then run this script again. It re-checks before storing.

MSG
  exit 1
fi
echo "  ok - refresh grant accepted"

# Braces matter here: a bare $REPO followed by a multi-byte character (the
# ellipsis) lets bash read those bytes as part of the variable name, which under
# `set -u` dies with "unbound variable".
echo "→ Storing it as GitHub secret SFDX_AUTH_URL on ${REPO}..."
printf '%s' "$AUTH_URL" | gh secret set SFDX_AUTH_URL --repo "$REPO"

echo "→ Triggering a test run…"
gh workflow run keepalive.yml --repo "$REPO" >/dev/null 2>&1 || true

echo "✓ Done. The org will now be pinged every Monday. Watch the first run at:"
echo "  https://github.com/$REPO/actions/workflows/keepalive.yml"
