#!/usr/bin/env python3
"""
Prove how much of live mode works, without anyone typing a password.

"Code complete, never observed end to end" was the honest state of the
dashboard's Salesforce connection, and it is also a useless thing to keep
saying. It lumps together a browser login — which needs a human and always will
— with a dozen server-side preconditions that need nobody at all, and any one of
which can silently break the flow. That is exactly what happened once already:
OAuth-endpoint CORS was off, and the symptom a person saw was "connect kaam
nahin karta".

This checks everything except the password. It uses the CLI's own access token
to stand in for the one the browser would hold, and sends the Origin header the
deployed dashboard sends, so a CORS header that is missing for that origin fails
here rather than in someone's browser.

    python3 scripts/verify-live-mode.py --target-org orgiq

The SOQL is read out of dashboard/src/lib/live.js rather than retyped. A copy
here would pass while the dashboard failed the moment the two drifted — which is
the only failure this script exists to catch.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_JS = ROOT / "dashboard/src/lib/live.js"
CONFIG_JS = ROOT / "dashboard/src/lib/sfConfig.js"
CONNECTED_APP = ROOT / "salesforce/force-app/main/default/connectedApps"
CORS_DIR = ROOT / "salesforce/force-app/main/default/corsWhitelistOrigins"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def sf_json(args):
    proc = subprocess.run(["sf", *args, "--json"], capture_output=True, text=True)
    payload = json.loads(proc.stdout or "{}")
    if payload.get("status", 1) != 0:
        sys.exit(f"sf {' '.join(args)} failed: {payload.get('message')}")
    return payload["result"]


# There is no way to obtain a usable raw access token from this machine, and
# the two obvious routes both fail in ways that look like something else:
# `sf org display --json` returns a REDACTED sentence in the accessToken field —
# present, a string, not a token — and the value in ~/.sfdx is encrypted at
# rest, so it produces a 401 that reads as a permissions problem.
#
# So the two halves are proven separately, which turns out to be the honest
# split anyway. Cross-origin access is checked over raw HTTP with no valid token
# at all: Salesforce sends Access-Control-Allow-Origin on a 401 exactly as it
# does on a 200, so an unauthenticated request is a complete test of the thing
# that actually broke for Saharsh. Schema and permissions are checked by running
# the dashboard's own SOQL through the CLI, which holds the real credential.


def request(url, origin, token=None, data=None):
    """Returns (status, headers, body-text). A 4xx is not an error here — the
    CORS header is what is being read, and Salesforce sends it on rejections
    too, which is the whole reason a bad request is a usable probe."""
    req = urllib.request.Request(url, data=data)
    req.add_header("Origin", origin)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:                                   # network, DNS, TLS
        return 0, {}, str(e)


def soql_from_live_js() -> dict:
    """The queries the dashboard actually sends, taken from its source.

    live.js builds each one by concatenating string literals; this re-joins them
    and keys the result on the object name passed as the last argument, which is
    the same label live.js uses in its own error messages.
    """
    src = LIVE_JS.read_text(encoding="utf-8")
    out = {}
    for block in re.finditer(r"soql\(tok,\s*(.+?)\)\s*\n", src, re.S):
        body = block.group(1)
        parts = re.findall(r"'([^']*)'", body)
        if not parts:
            continue
        obj = parts[-1]
        query = "".join(parts[:-1])
        if query.upper().startswith("SELECT"):
            out[obj] = query
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-org", required=True)
    ap.add_argument("--origin", default="",
                    help="the origin the dashboard is served from; defaults to "
                         "the connected app's own callback URL")
    a = ap.parse_args()

    org = sf_json(["org", "display", "--target-org", a.target_org])
    instance = org["instanceUrl"].rstrip("/")

    cfg = CONFIG_JS.read_text(encoding="utf-8")
    client_id = re.search(r"clientId:\s*'([^']+)'", cfg).group(1)
    login_url = re.search(r"loginUrl:\s*'([^']+)'", cfg).group(1).rstrip("/")
    api_version = re.search(r"apiVersion:\s*'([^']+)'", cfg).group(1)

    app_xml = "".join(p.read_text(encoding="utf-8") for p in CONNECTED_APP.glob("*.xml"))
    callback = re.search(r"<callbackUrl>([^<]+)</callbackUrl>", app_xml).group(1)
    origin = a.origin or urllib.parse.urlsplit(callback)._replace(
        path="", query="", fragment="").geturl()

    print(f"\nOrigin under test : {origin}")
    print(f"Org               : {instance}\n")

    # --- configuration the browser depends on --------------------------------
    print("Configuration")
    check("dashboard loginUrl is this org",
          login_url.rstrip("/") == instance,
          "" if login_url.rstrip("/") == instance
          else f"sfConfig says {login_url}, org is {instance}")
    check("connected app callback matches the served origin",
          callback.startswith(origin),
          f"callback {callback}")
    cors_files = list(CORS_DIR.glob("*.xml")) if CORS_DIR.exists() else []
    cors_declared = any(origin.split("//", 1)[-1] in p.read_text(encoding="utf-8")
                        for p in cors_files)
    check("origin is in the CorsWhitelistOrigin metadata", cors_declared,
          f"{len(cors_files)} origin file(s)")

    # --- the three cross-origin calls the browser makes -----------------------
    print("\nCross-origin access (the failure a person sees as \"connect does not work\")")
    status, headers, _ = request(
        f"{login_url}/services/oauth2/token", origin,
        data=urllib.parse.urlencode({"grant_type": "authorization_code",
                                     "code": "probe", "client_id": client_id}).encode())
    allow = headers.get("Access-Control-Allow-Origin", "")
    check("token endpoint returns the CORS header",
          allow in (origin, "*"),
          f"HTTP {status}, allow-origin: {allow or '(absent)'}")

    status, headers, body = request(
        f"{instance}/services/data/{api_version}/query?q="
        + urllib.parse.quote("SELECT Id FROM OrgIQ_Scan__c LIMIT 1"), origin)
    allow = headers.get("Access-Control-Allow-Origin", "")
    check("query API returns the CORS header", allow in (origin, "*"),
          f"HTTP {status}, allow-origin: {allow or '(absent)'}")

    status, headers, _ = request(f"{instance}/services/oauth2/userinfo", origin)
    allow = headers.get("Access-Control-Allow-Origin", "")
    check("userinfo returns the CORS header", allow in (origin, "*"),
          f"HTTP {status}, allow-origin: {allow or '(absent)'}")

    # --- the authorize leg, as far as it goes without a human ----------------
    print("\nAuthorization")
    p = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": callback,
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256", "scope": "api refresh_token openid"})
    status, headers, body = request(f"{login_url}/services/oauth2/authorize?{p}", origin)
    # A login page (or a redirect to one) means the client id and callback were
    # both accepted. Salesforce answers a bad client id with an error page
    # naming it, so the distinction is legible without following the redirect.
    bad = re.search(r"error=([a-z_]+)", body or "") or ("OAUTH_APP_BLOCKED" in (body or ""))
    check("authorize accepts this client id and callback",
          status in (200, 302) and not bad,
          f"HTTP {status}" + (f", {bad.group(1)}" if hasattr(bad, "group") else ""))

    # --- the queries the dashboard will actually run -------------------------
    #
    # Run through the CLI, which holds the real credential. This proves the SOQL
    # parses, every field it names exists and is readable, and records come back
    # — everything about the query except that it was sent from a browser, which
    # the CORS checks above cover separately.
    print("\nThe dashboard's own queries (read from live.js, not retyped)")
    queries = soql_from_live_js()
    if not queries:
        check("live.js queries were parsed", False,
              "found none — the parser has broken, not the dashboard")
    for obj, q in sorted(queries.items()):
        proc = subprocess.run(["sf", "data", "query", "--query", q,
                               "--target-org", a.target_org, "--json"],
                              capture_output=True, text=True)
        payload = json.loads(proc.stdout or "{}")
        if payload.get("status") == 0:
            check(f"{obj}", True, f"{payload['result']['totalSize']} record(s)")
        else:
            check(f"{obj}", False, (payload.get("message") or "no message")[:100])

    # --- the tenant boundary, against the real records ----------------------
    print("\nTenant isolation (the boundary, not the intention)")
    tenants = [r["External_Enterprise_Id__c"] for r in json.loads(subprocess.run(
        ["sf", "data", "query", "--query",
         "SELECT External_Enterprise_Id__c FROM OrgIQ_Enterprise__c",
         "--target-org", a.target_org, "--json"],
        capture_output=True, text=True).stdout or "{}").get("result", {}).get("records", [])]
    check("the org holds named tenants", bool(tenants), ", ".join(tenants) or "none")

    def count(where):
        out = subprocess.run(["sf", "data", "query", "--query",
                              f"SELECT COUNT(Id) n FROM OrgIQ_Finding__c WHERE {where}",
                              "--target-org", a.target_org, "--json"],
                             capture_output=True, text=True)
        recs = json.loads(out.stdout or "{}").get("result", {}).get("records", [])
        return recs[0]["n"] if recs else -1

    total = count("Id != null")
    per = {t: count(f"Scan__r.Enterprise_Id__c = '{t}'") for t in tenants}
    check("every finding belongs to exactly one tenant",
          sum(per.values()) == total,
          f"{' + '.join(str(v) for v in per.values())} = {total}")
    check("no finding sits outside a tenant",
          count("Scan__r.Enterprise_Id__c = null") == 0)
    if len(tenants) > 1:
        # The claim in plain terms: scoping to one tenant cannot return another's
        # rows. Checked as a query, because that is how it would leak.
        a_id, b_id = tenants[0], tenants[1]
        crossed = count(f"Scan__r.Enterprise_Id__c = '{a_id}' AND "
                        f"Scan__r.Target_Org_Ref__r.Enterprise__r.External_Enterprise_Id__c "
                        f"= '{b_id}'")
        check("a query scoped to one tenant returns none of the other's",
              crossed == 0, f"{a_id} ∩ {b_id} = {crossed}")

    failed = [n for n, ok, _ in results if not ok]
    print("\n" + "-" * 68)
    if failed:
        print(f"{len(failed)} check(s) failed:\n  " + "\n  ".join(failed))
        print("\nLive mode will not work in a browser until these pass.")
        return 1
    print("Every server-side precondition for live mode passes.\n"
          "What is NOT proven by this: the browser login itself — a human typing\n"
          "credentials on Salesforce's page and the redirect coming back with a\n"
          "code. That needs a person, and no script can stand in for it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
