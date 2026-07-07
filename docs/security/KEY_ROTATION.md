# API Key Rotation — JARVIS TRADER

> **Status:** The Anthropic API key is present in git history.
> Rotate it before any public exposure (open-source, CI, external collaborators).

---

## Why rotate

- **Exposure surface:** any secret committed to a git repo — even once, even reverted — must be treated as compromised. `git log -p` can recover it.
- **Cost risk:** Anthropic keys carry billing attached to Matt's personal account. A leaked key is a blank check.
- **Blast radius:** the same key is used by the engine's pipeline LLMs, the debate orchestrator, and Opus advisor calls. Revoking without planning will halt all paper trading until the new key is in `engine/.env`.

---

## What you rotate

Only one key as of 2026-04-10:

| Name                  | Where used                                                     | Where stored       |
| --------------------- | -------------------------------------------------------------- | ------------------ |
| `ANTHROPIC_API_KEY`   | `engine/agents/*.py` (via `anthropic.Anthropic()`)             | `engine/.env` only |

**There are no other hardcoded copies.** Verify with:

```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
grep -r "sk-ant-" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md" . 2>/dev/null
```

If that grep returns anything outside `engine/.env` or this doc, STOP and clean it up first.

---

## Rotation procedure

### Step 1 — Create a new key

1. Open https://console.anthropic.com/settings/keys
2. Click **Create Key**
3. Name it `jarvis-trader-2026-04-10` (or similar — include a date)
4. Copy the key (`sk-ant-…`) to your clipboard. **Do NOT paste it into any file.**

### Step 2 — Run the rotation script

From the repo root in PowerShell:

```powershell
.\scripts\rotate_anthropic_key.ps1
```

The script will:

1. Prompt for the new key (hidden input — `Read-Host -AsSecureString`)
2. Back up `engine/.env` to `engine/.env.bak-<timestamp>`
3. Replace (or append) the `ANTHROPIC_API_KEY=…` line
4. Verify the new key by calling `claude-haiku-4-5-20251001` with a 10-token ping
5. On success: restart the engine via `.\restart_engine.ps1`
6. On failure: restore the backup and exit with a clear error

**At no point is the plaintext key written to logs, stdout, or anywhere except `engine/.env`.**

### Step 3 — Verify the engine is healthy

```bash
curl http://localhost:8010/health
# Expect: 200 with status={"ok": true, ...}

curl -X POST http://localhost:8010/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MES","interval":"1h"}'
# Expect: 200 with a pipeline result, NO "401 invalid_api_key" in engine logs.
```

Watch the engine log for any `401 authentication_error` — that indicates the old key is still cached somewhere.

### Step 4 — Revoke the old key

1. Go back to https://console.anthropic.com/settings/keys
2. Find the old key (usually the one NOT named `jarvis-trader-2026-04-10`)
3. Click **Revoke**
4. Confirm the revoke

Once revoked, the old key value becomes useless even if an attacker recovers it from git history.

### Step 5 — Clean up the backup

After 24 hours of stable operation with the new key:

```powershell
Remove-Item engine\.env.bak-*
```

Keep the backup until you're confident the new key is stable, but do not commit it.

---

## Git history scrub (optional, destructive)

If you need to remove the key from git history entirely (for example, before open-sourcing), use [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/):

```bash
# One-time setup
brew install bfg  # macOS, or download .jar

# Find secrets
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
git clone --mirror . ../jarvis-trader-mirror.git
cd ../jarvis-trader-mirror.git

# Create a replacements file
echo 'sk-ant-api03-REDACTED' > /tmp/replacements.txt
bfg --replace-text /tmp/replacements.txt

# Cleanup
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Push — WARNING: force-push rewrites history for everyone
# Do NOT do this if the repo has collaborators or is published
cd ../jarvis-trader
git push --force --all origin  # DANGEROUS
git push --force --tags origin # DANGEROUS
```

**Warnings:**

1. Force-pushing rewrites history — anyone who has a clone of the repo must re-clone.
2. BFG does NOT remove the key from GitHub's web cache or from forks — you'd need to contact GitHub support and delete forks.
3. **Revoking the key at the console makes this step unnecessary in most cases.** Only do the scrub if you're publishing the repo or have concrete reason to believe the key is still being used by an attacker.

---

## Future rotations

Set a recurring calendar reminder: **rotate every 90 days**, or immediately after any of:

- A collaborator leaves the project
- The key is pasted into any external tool (chat, email, ticket)
- An unexpected Anthropic billing spike
- A new deployment surface is added (CI, Docker, hosted dashboard)

Keep this doc up to date with the list of places the key lives.
