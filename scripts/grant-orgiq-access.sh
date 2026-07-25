#!/usr/bin/env bash
#
# Give a colleague live-mode access to the OrgIQ dashboard.
#
#   bash scripts/grant-orgiq-access.sh <username>            # org alias "orgiq"
#   bash scripts/grant-orgiq-access.sh <username> <alias>     # a different org
#
# Live mode reads OrgIQ_Scan__c / OrgIQ_Finding__c / OrgIQ_Dimension_Score__c
# straight from the OrgIQ org in the browser. Signing in is not enough: without
# the OrgIQ_Admin permission set the queries come back refused and the dashboard
# falls back to demo data. This script assigns that permission set and verifies
# it landed.
#
# It does NOT create the user. Creating one needs a real name, email and profile
# — the org owner's call, not a script's — so if the username is not in the org
# this stops and says how to create it.
#
# Run it as the org owner (or any admin), on a machine where `sf` is
# authenticated to the org. Nothing here prints a token or a password.

set -euo pipefail

PERMSET="OrgIQ_Admin"
DASHBOARD="https://singhaditya21.github.io/SFORGIQ/"

USERNAME="${1:-}"
ORG="${2:-orgiq}"

if [ -z "$USERNAME" ]; then
  echo "usage: bash scripts/grant-orgiq-access.sh <salesforce-username> [org-alias]"
  echo
  echo "  <salesforce-username>  the colleague's Salesforce username in the OrgIQ org."
  echo "                         It looks like an email but is a separate, globally"
  echo "                         unique login (often name@company.com.orgiq)."
  echo "  [org-alias]            sf CLI alias for the OrgIQ org (default: orgiq)."
  exit 2
fi

command -v sf >/dev/null || { echo "Salesforce CLI (sf) not found — install it first."; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found (used only to read the CLI's JSON)."; exit 1; }

# Read one field out of an `sf ... --json` payload. Missing/!=0 status prints
# nothing, so every caller has to handle the empty case rather than trusting it.
jget() {   # jget <json> <python-expression-over-`r`(result)>
  printf '%s' "$1" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if d.get('status') != 0:
    sys.exit(0)
r = d.get('result') or {}
try:
    v = $2
except Exception:
    v = None
print('' if v is None else v)
" 2>/dev/null || true
}

# SOQL string literals: escape backslash first, then the quote. Usernames are
# tightly constrained by Salesforce, but this value comes from the command line
# and is pasted into a query, so it gets escaped like any other untrusted input.
SOQL_USERNAME=$(printf '%s' "$USERNAME" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g")

query() {  # query <soql> -> raw --json payload (empty on failure)
  sf data query --target-org "$ORG" --query "$1" --json 2>/dev/null || true
}

echo "→ Checking the org connection (alias '$ORG')…"
ORG_JSON=$(sf org display --target-org "$ORG" --json 2>/dev/null || true)
ORG_USER=$(jget "$ORG_JSON" "r.get('username')")
INSTANCE=$(jget "$ORG_JSON" "r.get('instanceUrl')")
if [ -z "$ORG_USER" ]; then
  echo "  Could not reach org '$ORG'."
  echo "  Authenticate first:  sf org login web --alias $ORG"
  exit 1
fi
echo "  Connected to $INSTANCE as $ORG_USER"

echo "→ Checking that the $PERMSET permission set exists in this org…"
PS_JSON=$(query "SELECT Id FROM PermissionSet WHERE Name = '$PERMSET'")
PS_ID=$(jget "$PS_JSON" "(r.get('records') or [{}])[0].get('Id')")
if [ -z "$PS_ID" ]; then
  echo "  '$PERMSET' is not in this org, so there is nothing to assign."
  echo "  Deploy OrgIQ's metadata first:"
  echo "    sf project deploy start --source-dir salesforce/force-app --target-org $ORG"
  exit 1
fi

echo "→ Looking up '$USERNAME'…"
U_JSON=$(query "SELECT Id, Name, IsActive FROM User WHERE Username = '$SOQL_USERNAME'")
USER_ID=$(jget "$U_JSON" "(r.get('records') or [{}])[0].get('Id')")
USER_NAME=$(jget "$U_JSON" "(r.get('records') or [{}])[0].get('Name')")
USER_ACTIVE=$(jget "$U_JSON" "(r.get('records') or [{}])[0].get('IsActive')")

if [ -z "$USER_ID" ]; then
  cat <<EOF
  No user with username '$USERNAME' exists in this org.

  This script does not create users on purpose — a new user needs a real name,
  email, profile and licence, and that is your call, not a script's. Create it
  by hand, then run this again:

    1. Setup → Users → Users → New User.
    2. Give it a licence with API access (Salesforce, or Salesforce Platform).
    3. Salesforce usernames are globally unique across ALL orgs and look like an
       email without being one — if 'name@company.com' is taken, use something
       like 'name@company.com.orgiq'.
    4. Salesforce emails them an activation link; they set their own password.
       You never handle it, and neither does this script.
    5. Re-run:  bash scripts/grant-orgiq-access.sh <the-username-you-chose> $ORG
EOF
  exit 1
fi

if [ "$USER_ACTIVE" != "True" ] && [ "$USER_ACTIVE" != "true" ]; then
  echo "  Found $USER_NAME ($USER_ID), but the user is INACTIVE."
  echo "  Reactivate it in Setup → Users before granting access; an inactive user cannot log in."
  exit 1
fi
echo "  Found $USER_NAME ($USER_ID), active."

echo "→ Checking for an existing $PERMSET assignment…"
A_JSON=$(query "SELECT Id FROM PermissionSetAssignment WHERE PermissionSetId = '$PS_ID' AND AssigneeId = '$USER_ID'")
ALREADY=$(jget "$A_JSON" "(r.get('records') or [{}])[0].get('Id')")

if [ -n "$ALREADY" ]; then
  echo "  Already assigned — nothing to change."
else
  echo "→ Assigning $PERMSET to $USERNAME…"
  # --on-behalf-of is what assigns to somebody else; without it the CLI assigns
  # to the authenticated admin, which is never what anyone running this wants.
  # It resolves its value as a username OR a CLI alias, so when that resolution
  # is the thing that fails, fall back to inserting the assignment record —
  # both ids are already in hand and PermissionSetAssignment is just a row.
  if ! sf org assign permset --name "$PERMSET" --target-org "$ORG" --on-behalf-of "$USERNAME" >/dev/null 2>&1; then
    echo "  The CLI's assign command did not take — inserting the assignment record directly…"
    sf data create record --target-org "$ORG" --sobject PermissionSetAssignment \
      --values "AssigneeId=$USER_ID PermissionSetId=$PS_ID" >/dev/null 2>&1 || true
  fi
fi

# Verify against the org rather than trusting the exit code — an assignment that
# did not land must not be reported as access granted.
echo "→ Verifying…"
V_JSON=$(query "SELECT Id FROM PermissionSetAssignment WHERE PermissionSetId = '$PS_ID' AND AssigneeId = '$USER_ID'")
VERIFIED=$(jget "$V_JSON" "(r.get('records') or [{}])[0].get('Id')")
if [ -z "$VERIFIED" ]; then
  echo "  Could not confirm the assignment by querying it back — so it did NOT land,"
  echo "  and $USER_NAME still cannot see OrgIQ data. Re-running the assignment with"
  echo "  full output so the reason is visible:"
  echo
  sf org assign permset --name "$PERMSET" --target-org "$ORG" --on-behalf-of "$USERNAME" || true
  echo
  echo "  You can also check by hand: Setup → Users → $USER_NAME → Permission Set Assignments"
  exit 1
fi

SCANS=$(jget "$(query 'SELECT COUNT(Id) c FROM OrgIQ_Scan__c')" "(r.get('records') or [{}])[0].get('c')")

cat <<EOF
✓ Verified: $USER_NAME holds $PERMSET and can read OrgIQ data in this org.

  Tell them to:
    1. Open $DASHBOARD
    2. Hard-refresh (Cmd/Ctrl + Shift + R) — the old page may hold a stale session.
    3. Click "Connect Salesforce" and sign in as $USERNAME.

  If they had already connected and were seeing demo data, "Re-check live access"
  on the dashboard picks up this grant without signing in again.
EOF

if [ -n "$SCANS" ] && [ "$SCANS" = "0" ]; then
  cat <<EOF

  Note: this org currently holds 0 scans, so they will sign in successfully and
  still see nothing to display. Load a portfolio first:
    python3 salesforce/load_portfolio.py
EOF
elif [ -n "$SCANS" ]; then
  echo
  echo "  This org holds $SCANS scan(s) for them to see."
fi
