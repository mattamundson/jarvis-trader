# Security P0 — API Key Rotation Checklist

**Priority**: CRITICAL — Must complete before Phase 3 live trading
**Reason**: API keys were exposed in git history during development
**Last updated**: 2026-04-02

---

## Why This Is Critical

Git history is permanent. Even after deleting or gitignoring a file, every historical
commit that ever contained a secret is permanently readable by anyone with access to the
repository — including anyone who cloned it before or after the deletion.

**Removing the file from the working tree does NOT remove it from history.**
The only remediation is:
1. REVOKE the exposed keys immediately (makes them useless even if found in history)
2. Generate new keys and populate `engine/.env` with the fresh values
3. (Optional but recommended) Scrub git history using BFG Repo Cleaner or git-filter-repo

Revoking keys is the non-negotiable step. History scrubbing is best-effort cleanup.

---

## Exposed Credentials (Confirmed in Git History)

| Credential | Format | Risk if Exploited |
|------------|--------|-------------------|
| Anthropic API Key | `sk-ant-api03-...` | LLM inference billed to your account |
| Polygon.io API Key | opaque string | Market data quota consumed |
| Twilio Account SID + Auth Token | `AC...` + token | WhatsApp/SMS billed to your account |
| Google OAuth Client Secret | `client_secret*.json` | OAuth app impersonation |

---

## Step-by-Step Rotation

### 1. Anthropic API Key

**URL**: https://console.anthropic.com/settings/keys

**Steps**:
1. Log in to the Anthropic Console
2. Navigate to API Keys in the left sidebar
3. Find the key matching the `sk-ant-api03-...` pattern
4. Click the three-dot menu next to it
5. Select "Revoke Key" and confirm — it will show "Revoked" status
6. Click "Create Key"
7. Name it: `JARVIS TRADER (Post-Audit 2026-04)`
8. Copy the new key immediately (it is only shown once)

**Env var to update**: `ANTHROPIC_API_KEY` in `engine/.env`

**Verify old key is dead** (should return 401):
```bash
curl -s -X GET https://api.anthropic.com/v1/models \
  -H "x-api-key: [REDACTED]" | python -m json.tool
```

**Verify new key works**:
```bash
curl -s -X POST https://api.anthropic.com/v1/messages \
  -H "x-api-key: [REDACTED]" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}'
```

---

### 2. Polygon.io API Key

**URL**: https://polygon.io/dashboard/api-keys

**Steps**:
1. Log in to Polygon.io
2. Navigate to Dashboard -> API Keys
3. Find the active key and click "Revoke" or "Delete"
4. Click "Create New API Key"
5. Copy the new key

**Env var to update**: `POLYGON_API_KEY` in `engine/.env`

**Verify new key works**:
```bash
curl -s "https://api.polygon.io/v2/aggs/ticker/SPY/prev?adjusted=true&apiKey=[REDACTED]" \
  | python -m json.tool | head -20
```

Expected: JSON response with `"status": "OK"` and ticker results.

---

### 3. Finnhub API Key

**URL**: https://finnhub.io/dashboard

**Steps**:
1. Log in to Finnhub
2. Go to Dashboard -> API Keys
3. Click "Regenerate" on the existing key (this revokes the old one)
4. Copy the new key

**Env var to update**: `FINNHUB_API_KEY` in `engine/.env`

**Verify new key works**:
```bash
curl -s "https://finnhub.io/api/v1/quote?symbol=SPY&token=[REDACTED]" \
  | python -m json.tool
```

Expected: JSON with `"c"` (current price) field populated.

---

### 4. Twilio Credentials

**URL**: https://console.twilio.com/us1/account/manage-account/general-settings

**Steps**:
1. Log in to Twilio Console
2. Navigate to Account -> API Credentials section
3. The primary Auth Token can be rotated: click "Regenerate primary auth token"
4. Confirm the rotation — this immediately invalidates the old token
5. Copy both the Account SID and the new Auth Token

Note: The Account SID (`ACxxxxxxxx`) is a public identifier, not a secret.
The Auth Token is the actual credential that must be rotated.

**Env vars to update** in `engine/.env`:
```ini
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=<new-auth-token>
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+1XXXXXXXXXX
```

**Verify WhatsApp alert still works** (after engine restart):
```bash
curl -s -X POST http://localhost:8010/notifications/whatsapp/test \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json"
```

---

### 5. Google OAuth Credentials (if used)

**URL**: https://console.cloud.google.com/apis/credentials

**Steps**:
1. Log in to Google Cloud Console
2. Select the project (valued-road-491703-p0)
3. Find the OAuth 2.0 Client ID (Desktop application)
4. Click on it -> "Reset Secret" (or delete and recreate)
5. Download the new credentials JSON
6. Rename to: `client_secret_JARVIS_REGENERATED.json`
7. Store it OUTSIDE the repo directory (e.g. `C:\Users\mattm\jarvis-secrets\`)

**Verify**: The old `client_secret*.json` file in the repo should already be gitignored.
Confirm:
```bash
git check-ignore -v client_secret*.json
```

---

### 6. Alpaca API Keys (if used)

**URL**: https://app.alpaca.markets/paper/dashboard/overview

**Steps**:
1. Log in to Alpaca paper trading dashboard
2. Navigate to API Keys section
3. Click "Regenerate" on existing keys
4. Copy the new API key and secret key

**Env vars to update** in `engine/.env`:
```ini
ALPACA_API_KEY=<new-key>
ALPACA_SECRET_KEY=<new-secret>
ALPACA_PAPER=True
```

---

### 7. FRED API Key (if used)

**URL**: https://fredaccount.stlouisfed.org/apikeys

**Steps**:
1. Log in to your FRED account
2. Navigate to My Account -> API Keys
3. Request a new key (FRED does not have a regenerate button — request a new one)
4. Optionally delete the old key from the same page

**Env var to update**: `FRED_API_KEY` in `engine/.env`

**Verify**:
```bash
curl -s "https://api.stlouisfed.org/fred/series?series_id=GDP&api_key=[REDACTED]" \
  | python -m json.tool | head -10
```

---

### 8. Internal Engine API Key

The engine and dashboard share a `API_KEY` for request authentication. The defaults
(`test-key`, `jarvis-dev-key-change-me`) are not externally exposed but should be
rotated to a strong random value.

**Generate a new key** (PowerShell):
```powershell
[System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

**Update both locations**:
- `engine/.env`: `API_KEY=[REDACTED]
- `dashboard/.env.local`: `NEXT_PUBLIC_ENGINE_API_KEY=<same-generated-value>`

**Verify old key is rejected** (should return 401):
```bash
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: test-key" http://localhost:8010/health
```

**Verify new key is accepted** (should return 200):
```bash
curl -s -w "\nHTTP %{http_code}\n" -H "X-API-Key: $API_KEY" http://localhost:8010/health
```

---

## After All Keys Rotated

Run these steps in order to confirm the engine is fully operational with new credentials:

**Step 1 — Restart the engine:**
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv/Scripts/python -m uvicorn main:app --port 8010
```

Watch startup logs. You should see clean initialization with no "missing env var" errors.

**Step 2 — Health check:**
```bash
curl -s http://localhost:8010/health | python -m json.tool
```

Expected: `"status": "healthy"` with subsystems reporting green.

**Step 3 — Pipeline test** (validates Anthropic key end-to-end):
```bash
curl -s -X POST http://localhost:8010/pipeline/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"symbol": "MCL", "interval": "1h"}' \
  | python -m json.tool
```

**Step 4 — WhatsApp notification test** (validates Twilio credentials):
```bash
curl -s -X POST http://localhost:8010/notifications/whatsapp/test \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json"
```

---

## Git History Note

Revoking keys makes the leaked credentials useless even if someone extracts them from git
history. The git history itself still contains the old key values until you explicitly
rewrite it.

For a solo project, history rewriting is optional but strongly recommended before Phase 3.
Use one of the following options:

**Option A — BFG Repo Cleaner** (faster, requires Java):
```bash
# Create a mirror clone first
cd /tmp && git clone --mirror C:/Users/mattm/ThinkorSwim/jarvis-trader jarvis-trader.git

# Create a file listing the exact secret strings to replace
cat > /tmp/secrets.txt << 'SECRETS'
[REDACTED_ANTHROPIC_KEY]
YOURPOLYGONKEYVALUE
YOURTWILIOAUTHTOKEN
SECRETS

# Run BFG to replace secrets with ***REMOVED***
java -jar bfg.jar --replace-text /tmp/secrets.txt jarvis-trader.git

# Expire reflogs and compact
cd jarvis-trader.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force-push to remote (if any)
git push --force --all
git push --force --tags
```

**Option B — git-filter-repo** (no Java required, nuclear option — removes entire .env history):
```bash
pip install git-filter-repo
git filter-repo --path engine/.env --invert-paths
git push --force --all
```

WARNING: Both options rewrite history. All collaborators must re-clone after a force-push.

See `docs/runbooks/SECURITY_REMEDIATION.md` for the full step-by-step BFG walkthrough.

---

## Verification Checklist

Complete all items below before declaring security remediation done:

- [ ] Anthropic key revoked at https://console.anthropic.com/settings/keys
- [ ] New Anthropic key generated and added to `engine/.env`
- [ ] Anthropic key verified working (curl messages endpoint returns 200)
- [ ] Polygon key revoked at https://polygon.io/dashboard/api-keys
- [ ] New Polygon key generated and added to `engine/.env`
- [ ] Polygon key verified working (ticker query returns OK status)
- [ ] Finnhub key regenerated and added to `engine/.env`
- [ ] Finnhub key verified working (quote endpoint returns price data)
- [ ] Twilio Auth Token rotated at https://console.twilio.com
- [ ] New Twilio credentials added to `engine/.env`
- [ ] WhatsApp test alert fires successfully
- [ ] Google OAuth credentials reset (if applicable — valued-road-491703-p0)
- [ ] Alpaca keys regenerated (if applicable)
- [ ] FRED key regenerated (if applicable)
- [ ] Internal `API_KEY` rotated to a strong random value in both env files
- [ ] Engine starts clean with no missing-env-var errors
- [ ] Health check returns healthy
- [ ] Pipeline test completes successfully on MCL 1h
- [ ] Git history scrub completed (or explicitly deferred with date and reason)
- [ ] Pre-commit secrets hook verified active: `ls .git/hooks/pre-commit`

---

## Reference Docs

| Document | Location |
|----------|----------|
| Full SECURITY_REMEDIATION guide | `docs/runbooks/SECURITY_REMEDIATION.md` |
| API key rotation details | `docs/runbooks/API_KEY_ROTATION.md` |
| Env vars reference | `engine/.env.example` |
| Safety rules | `.claude/rules/safety.md` |
| Pre-commit secrets hook | `scripts/hooks/check-secrets.sh` |
