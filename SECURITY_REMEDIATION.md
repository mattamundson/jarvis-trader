# Security Remediation Guide — US-001

**Status:** CRITICAL — API keys exposed in git history

This guide provides step-by-step instructions for Matt to revoke compromised API keys and regenerate secure credentials.

## Exposed Credentials

The following credentials were found in the git history and MUST be revoked immediately:

- **Anthropic API Key** (format: sk-ant-api03-...)
- **Polygon.io API Key**
- **Twilio Account SID and Auth Token**
- **Google OAuth Client ID and Secret** (client_secret_*.json)

---

## Step 1: Revoke Anthropic API Key

### Why:
The sk-ant-api03 key in the git history grants full access to the Anthropic API and can be used to make calls on your behalf.

### Steps:

1. Go to **[Anthropic Console](https://console.anthropic.com/account/keys)**
2. Click **"API Keys"** in the sidebar
3. Find the key matching the pattern in your git history (sk-ant-api03-...)
4. Click the **three-dot menu** next to it
5. Select **"Revoke Key"** and confirm
6. Verify it shows **"Revoked"** status

### Verification:
```bash
# Confirm the old key no longer works (should return 401)
curl -X GET https://api.anthropic.com/v1/models \
  -H "x-api-key: [REDACTED]"
```

---

## Step 2: Revoke Polygon.io API Key

### Why:
The Polygon API key grants access to real-time and historical market data. A compromised key could allow attackers to drain your quota or access your data.

### Steps:

1. Go to **[Polygon Dashboard](https://polygon.io/dashboard/api-keys)**
2. Log in with your Polygon account
3. Find the API key in the history or active keys list
4. Click **"Revoke"** or **"Delete"**
5. Confirm the revocation

### Verification:
```bash
# Confirm the old key no longer works (should return 401)
curl "https://api.polygon.io/v1/meta/symbols/AAPL?apiKey=[REDACTED]"
```

---

## Step 3: Revoke Twilio SID and Auth Token

### Why:
Twilio credentials grant full access to send SMS, WhatsApp messages, and make calls. A compromised key could allow attackers to send alerts from your account.

### Steps:

1. Go to **[Twilio Console](https://www.twilio.com/console)**
2. Navigate to **"Account"** → **"API Keys & Tokens"**
3. Look for any suspicious API keys or the exposed Auth Token
4. Click the key and select **"Delete"**
5. If you only have one Auth Token (the main account token), you cannot revoke it directly
   - Instead, **change your Account password** immediately:
     - Click **"Account Settings"** → **"Security"**
     - Enter a new, strong password
6. Verify your WhatsApp Sandbox is still active:
   - Go to **"Messaging"** → **"Try it out"** → **"WhatsApp Sandbox"**
   - Confirm your test number is still there

### Verification:
Test from the Twilio console or wait for the next scheduled WhatsApp message to fail.

---

## Step 4: Revoke Google OAuth Credentials

### Why:
Google OAuth client secrets grant access to Google APIs on your behalf. A compromised secret could allow attackers to read your Google Drive, Calendar, or Gmail.

### Steps:

1. Go to **[Google Cloud Console](https://console.cloud.google.com/apis/credentials)**
2. Select your project (valued-road-491703-p0)
3. Find the OAuth 2.0 Client ID with client secret (likely listed as "Desktop application")
4. Click on it to open details
5. Click the **"Delete"** button (trash icon) at the top
6. Confirm deletion
7. Create a new OAuth 2.0 Client ID:
   - Click **"+ Create Credentials"** → **"OAuth 2.0 Client ID"**
   - Choose **"Desktop application"**
   - Name it: "JARVIS TRADER (Regenerated)"
   - Click **"Create"**
8. Download the new credentials JSON file
9. Rename to: `client_secret_JARVIS_TRADER_REGENERATED.json`
10. Save it securely (NOT in the repo)

### Verification:
```bash
# Verify the old client_secret_*.json file in the repo is now just a stub
# It should still be in .gitignore and safe from commits
ls -la client_secret_*.json
```

---

## Step 5: Scrub Git History with BFG Repo-Cleaner

### Why:
Even with revoked keys, the exposed values still exist in git history. Any clone of the repo would expose them. BFG removes secrets from all commits, tags, and branches.

### Prerequisites:
```bash
# Install BFG (requires Java runtime)
brew install bfg  # macOS
# or on Linux: download from https://rtyley.github.io/bfg-repo-cleaner/

# Or use Docker
docker run --rm -v ~/.ssh:/root/.ssh -v /path/to/jarvis-trader:/tmp/repo \
  bfg/bfg --help
```

### Steps:

1. **Create a git mirror clone** (BFG works on a mirror):
```bash
cd /tmp
git clone --mirror /path/to/jarvis-trader jarvis-trader.git
cd jarvis-trader.git
```

2. **Create a secrets file to scan for**:
```bash
# Create /tmp/secrets.txt with patterns to remove
cat > /tmp/secrets.txt << 'EOF'
sk-ant-api03-.*
TWILIO_ACCOUNT_SID=.*
TWILIO_AUTH_TOKEN=.*
POLYGON_API_KEY=.*
client_secret.*
gocspx-.*
93934583212-.*
EOF
```

3. **Run BFG to remove secrets**:
```bash
bfg --replace-text /tmp/secrets.txt jarvis-trader.git
```

4. **Reflog expire and garbage collect**:
```bash
cd jarvis-trader.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

5. **Push the cleaned history back** (FORCE PUSH):
```bash
# In your working clone
cd /path/to/jarvis-trader

# Add the mirror as a remote
git remote add mirror /tmp/jarvis-trader.git

# Fetch all refs from the mirror (includes cleaned history)
git fetch mirror

# Force-push all branches back to the mirror
git push mirror --all --force
git push mirror --tags --force

# Force-push to GitHub (or your remote)
git push origin --all --force
git push origin --tags --force
```

**WARNING:** This will rewrite history. All collaborators must do a fresh clone.

---

## Step 6: Regenerate All API Keys and Populate .env

Now that old credentials are revoked, regenerate new ones.

### 6a: Generate New Anthropic API Key

1. Go to **[Anthropic Console](https://console.anthropic.com/account/keys)**
2. Click **"Create Key"**
3. Name it: "JARVIS TRADER (Post-Audit)"
4. Copy the new key (sk-ant-api03-...)
5. Add to `.env`:
```bash
ANTHROPIC_API_KEY=[REDACTED_ANTHROPIC_KEY]
```

### 6b: Generate New Polygon API Key

1. Go to **[Polygon Dashboard](https://polygon.io/dashboard/api-keys)**
2. Click **"Create New API Key"** or regenerate existing one
3. Copy the new key
4. Add to `.env`:
```bash
POLYGON_API_KEY=your_new_polygon_key_here
```

### 6c: Generate New Twilio Auth Token (or change password)

For a fresh start, consider creating a new API Key in Twilio:
1. Go to **[Twilio Console](https://www.twilio.com/console)**
2. Navigate to **"Account"** → **"API Keys & Tokens"**
3. Click **"Create API Key"** (separate from main Account Auth Token)
4. Name it: "JARVIS TRADER"
5. Copy the key and secret
6. Add to `.env`:
```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_new_twilio_token_here
TWILIO_WHATSAPP_FROM=+1234567890
WHATSAPP_TO=+1234567890
```

### 6d: Create New Google OAuth Credentials

1. Go to **[Google Cloud Console](https://console.cloud.google.com/apis/credentials)**
2. Create new OAuth 2.0 Client ID (see Step 4 above)
3. Download the JSON file
4. Store it securely (NOT in repo)
5. Reference in `.env` or application code (if needed)

### 6e: Populate Complete .env

Create or update `/path/to/jarvis-trader/.env` with all keys:

```bash
# Copy from .env.example and fill in real values
cp /path/to/jarvis-trader/.env.example /path/to/jarvis-trader/.env

# Edit .env and populate with new API keys
nano /path/to/jarvis-trader/.env
```

Verify all required keys are present:
```bash
# Should not output empty lines or "None"
grep -E "^(ANTHROPIC_API_KEY|POLYGON_API_KEY|TWILIO_ACCOUNT_SID|TWILIO_AUTH_TOKEN)" .env
```

---

## Step 7: Force-Push Cleaned History

This step assumes BFG was run in Step 5. Now we push the clean history to the remote.

```bash
cd /path/to/jarvis-trader

# Verify the local history is clean (should NOT contain exposed secrets)
git log -p --all | grep -i "sk-ant\|twilio_auth\|polygon_api" | wc -l
# Should output: 0

# Force-push to origin (GitHub, GitLab, etc.)
git push origin --all --force
git push origin --tags --force

# Notify all collaborators to do a fresh clone
```

**Collaborator Cleanup:**
Each developer who has a local clone should:
```bash
# Backup work if needed, then remove old clone
rm -rf ~/path/to/jarvis-trader

# Fresh clone
git clone git@github.com:your-org/jarvis-trader.git
```

---

## Step 8: Verify No Secrets Remain

Run comprehensive verification to ensure all secrets are gone.

### 8a: Check git history
```bash
cd /path/to/jarvis-trader

# Scan for Anthropic keys
git log -p --all | grep -i "sk-ant" | wc -l
# Expected: 0

# Scan for Twilio patterns
git log -p --all | grep -i "twilio_auth\|twilio_account" | wc -l
# Expected: 0

# Scan for Polygon patterns
git log -p --all | grep -i "polygon_api" | wc -l
# Expected: 0

# Scan for Google OAuth
git log -p --all | grep -i "gocspx\|client_secret" | wc -l
# Expected: 0
```

### 8b: Check for credential files in tracking
```bash
# Should be empty (all credential files in .gitignore)
git ls-files | grep -E "\.env$|\.env\..+|client_secret|credentials\.json"
# Expected: (no output)

# Check .gitignore is comprehensive
git check-ignore -v .env client_secret*.json *.pem
```

### 8c: Test API key revocation
```bash
# Verify old Anthropic key is dead
curl -s -X GET https://api.anthropic.com/v1/models \
  -H "x-api-key: [REDACTED]" | grep -i "unauthorized"
# Should show: unauthorized or 401 error
```

---

## Checklist for Completion

- [ ] Anthropic API key revoked at https://console.anthropic.com/account/keys
- [ ] Polygon API key revoked at https://polygon.io/dashboard/api-keys
- [ ] Twilio SID/Auth Token revoked or Twilio password changed at https://www.twilio.com/console
- [ ] Google OAuth credentials revoked at https://console.cloud.google.com/apis/credentials
- [ ] BFG Repo-Cleaner ran and cleaned git history
- [ ] Force-push completed: `git push origin --all --force`
- [ ] .env.example reviewed and populated with new placeholder values
- [ ] .env file created with all new API keys (NOT committed)
- [ ] .gitignore verified blocks .env, *.pem, credentials.json
- [ ] Verification passed: `git log -p --all | grep -i "sk-ant"` returns 0 results
- [ ] Pre-commit hook installed (see below)
- [ ] config.py validation added (see below)

---

## Additional Hardening

### Pre-commit Hook (Automatic Secret Detection)

See `scripts/check-secrets.sh` for automated secret scanning on every commit.

Install it:
```bash
chmod +x scripts/check-secrets.sh
ln -s ../../scripts/check-secrets.sh .git/hooks/pre-commit
```

### Config.py Validation (Startup Checks)

See `engine/config.py` — startup now validates all required env vars are set and non-empty. If any are missing, you'll get a clear error message with the variable name and description.

---

## Timeline

- **Immediately (Day 1):** Revoke all exposed keys (Steps 1-4)
- **Day 1-2:** BFG scrub and force-push (Steps 5-7)
- **Day 2:** Regenerate keys and verify (Steps 6-8)
- **Ongoing:** Use pre-commit hook and config validation to prevent future exposure

---

## Questions?

If you encounter issues during remediation:
1. Check BFG logs for errors
2. Verify git remote URL is correct before force-push
3. Ensure all API key services confirm revocation before proceeding
4. Keep .env file locally secured (chmod 600 .env)

Stay safe out there! 🔐
