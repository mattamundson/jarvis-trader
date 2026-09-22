# API Key Rotation Runbook

> Last updated: 2026-04-02
> Priority: P0 SECURITY — Act immediately. These keys are exposed in git history.

---

## 1. Exposed Keys in Git History

The following secrets were committed to the repository and MUST be revoked
immediately, even if the .env file is now gitignored. The keys exist in
historical commits and are permanently visible unless the git history is rewritten.

### 1a. Anthropic API Key

- **Key shape**: `sk-ant-api03-...` (full value was in history — treat as compromised)
- **Revoke at**: https://console.anthropic.com/account/keys
- **Action**: Log in, find the key in the list, click "Revoke". Generate a new key.
- **Impact**: Anyone with this key can run LLM inference billed to your account.

### 1b. Polygon.io API Key

- **Key shape**: opaque string from polygon.io (any key that ever lived in git history is compromised)
- **Revoke at**: https://polygon.io/dashboard/api-keys
- **Action**: Log in, locate the key, click "Revoke" or "Regenerate".
- **Impact**: Anyone with this key can consume your Polygon data quota.

### 1c. Twilio Account SID + Auth Token

- **Account SID**: Twilio `AC…` identifier (public-ish, but do not paste into docs)
- **Auth Token**: rotate if it ever appeared in git history
- **Revoke at**: https://console.twilio.com/us1/account/manage-account/general-settings
- **Action**: Under "API Credentials", click "Regenerate primary auth token".
  Twilio does not let you revoke the primary SID — rotating the auth token
  is sufficient as the token is the authentication credential.
- **Impact**: Anyone with these credentials can send WhatsApp/SMS messages
  billed to your account and read your message logs.

### 1d. Google OAuth Client Secret (if applicable)

- **Check for**: Any `client_secret*.json` files committed to the repo.
- **Revoke at**: https://console.cloud.google.com/apis/credentials
- **Action**: Select the OAuth 2.0 Client ID, click "Reset Secret".
- **Impact**: Anyone with the secret can impersonate your OAuth app.

---

## 2. Internal API Key (engine <-> dashboard)

The engine validates all non-exempt requests via the `X-API-Key` header.
The middleware is in `engine/middleware/api_key_middleware.py`.

### Current state (insecure)

```
engine/.env:            API_KEY=test-key
dashboard/.env.local:   NEXT_PUBLIC_ENGINE_API_KEY=test-key
engine/config.py:       default = "CHANGE_ME_BEFORE_DEPLOY"
```

The `.env` files are gitignored and never committed. The default in `config.py`
is now `"CHANGE_ME_BEFORE_DEPLOY"` — if you ever run without a `.env` file,
the engine will accept that literal string, making it obvious something is wrong.

### How to generate a strong replacement key

On Linux/macOS:
```bash
openssl rand -hex 32
```

On Windows (PowerShell):
```powershell
[System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Example output (do NOT use this — generate your own):
```
a3f9c2e1b8d74f6a2c5e9d0b7f3a1e4c8d2b6f0a9c3e7d1b5f8a2e4c6b0d9f3
```

---

## 3. Updating the .env Files

### Step 1 — Update engine/.env

Open `engine/.env` and replace the `API_KEY` line:

```ini
# Old (insecure)
API_KEY=test-key

# New (use your generated value)
API_KEY=[REDACTED]
```

### Step 2 — Update dashboard/.env.local

Open `dashboard/.env.local` and replace the matching line:

```ini
# Old (insecure)
NEXT_PUBLIC_ENGINE_API_KEY=test-key

# New (must match engine/.env exactly)
NEXT_PUBLIC_ENGINE_API_KEY=<your-generated-key-here>
```

### Step 3 — Restart both services

```bash
# Restart engine (from engine/ directory, using venv)
.venv/Scripts/python -m uvicorn main:app --port 8010

# Restart dashboard
cd dashboard && pnpm dev
```

---

## 4. Verifying the Change Worked

### Check that the old key is rejected

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: test-key" \
  http://localhost:8010/api/v1/health
```

Expected response: `401`

### Check that the new key is accepted

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -H "X-API-Key: <your-new-key>" \
  http://localhost:8010/api/v1/health
```

Expected response: HTTP `200` with a JSON health payload.

### Check that exempt paths still work (no key required)

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8010/health
```

Expected response: `200` — `/health` is in `EXEMPT_PATHS` and requires no key.

---

## 5. Exempt Paths (No API Key Required)

Defined in `engine/middleware/auth.py` as `EXEMPT_PATHS`. These paths bypass
key validation and are safe to call from monitoring tools without credentials:

- `/health`
- `/docs`
- `/redoc`
- `/openapi.json`
- `/metrics` (if Prometheus scraping is configured)

---

## 6. Security Notes

- `NEXT_PUBLIC_*` variables in Next.js are **bundled into client-side JavaScript**
  and visible to anyone who loads the dashboard in a browser. This is acceptable
  for a local development/paper trading setup where the dashboard is only accessible
  on localhost, but must be reconsidered before any public deployment.
- Never commit `.env` or `.env.local` — both are in `.gitignore`.
- The default fallback `"CHANGE_ME_BEFORE_DEPLOY"` in `config.py` is intentionally
  obvious so that a missing `.env` file causes visible misconfiguration rather than
  silently accepting a well-known weak key.
- After rotating all external keys, consider running `git log --all -S "sk-ant"` to
  confirm the old key exists in history, then decide whether to purge history using
  `git filter-repo` or BFG Repo Cleaner.

---

## 7. Git History Purge (Optional but Recommended)

If you want to remove the exposed secrets from git history entirely:

```bash
# Install BFG Repo Cleaner (https://rtyley.github.io/bfg-repo-cleaner/)
# Create a file listing secrets to remove, one per line:
echo "YOUR_ANTHROPIC_KEY_TO_PURGE" > secrets.txt
echo "YOUR_SECOND_SECRET_LINE" >> secrets.txt
echo "YOUR_THIRD_SECRET_LINE" >> secrets.txt
echo "YOUR_TWILIO_OR_OTHER_SID" >> secrets.txt

# Run BFG to replace secrets with "***REMOVED***"
java -jar bfg.jar --replace-text secrets.txt

# Force-push all branches and tags
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force --all
git push --force --tags
```

WARNING: This rewrites history. All collaborators must re-clone. Coordinate before
doing this in a shared repository.
