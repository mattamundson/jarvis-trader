# Security filename quarantine — 2026-09-24 — REMEDIATED 2026-09-25

## Status: payloads removed

The two credential exports previously stored in this directory as `*.archived` files have been
**deleted from the repository tree**. They contained plaintext infrastructure credentials:

| Key names found (values never printed) |
|---|
| `VERCEL_TOKEN`, `VERCEL_TEAM_ID` |
| `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID`, `RAILWAY_PROJECT_ID` |
| `ENGINE_API_KEY` |
| `DISCORD_WEBHOOK_URL` |

## Why the original approach was wrong

The original note here read:

> These tracked files were renamed from secret-shaped CSV filenames so the repository security scan
> no longer treats them as committed credential exports. […] the filenames no longer match the CI
> secret-filename denylist.

That is evasion, not remediation. The CI guard it was written to satisfy
(`Check for secret-shaped filenames` in `.github/workflows/ci.yml`) matches on **file names only**
(`*secret*.csv`, `*credential*.csv`, `*.pem`, …). Renaming `Secret-Value.csv` to
`value-export-root.archived` made the check pass while leaving the credential **bytes** committed —
the same plaintext secrets, now harder to notice. A filename denylist is not a control: the author
of a leak only has to change the name.

Renaming also removed the one signal that was working. The file went from "flagged by a simplistic
check" to "flagged by nothing."

## What replaced it

A content-based check, `scripts/check_credential_exports.py`, wired into CI as
**"Check for credential exports by content (filename-agnostic)"**. It matches the *shape* of an
export — a credential-shaped name paired with a long opaque value — so the file name is irrelevant.
It scans tracked non-documentation files and prints key names and locations, never values.

It is deliberately tuned to keep false positives near zero: documentation, `*.md`, `*.example`,
templates and the test tree are excluded, and a value must be at least 24 characters and look random
(mixed case or containing digits) before it counts.

## Still required (not fixable by deleting files)

Deleting from the tree does **not** remove these values from git history. They remain reachable in
earlier commits. Until the following are done, this is an open credential incident:

1. **Rotate every credential listed above** — Vercel token, Railway token, engine API key, Discord
   webhook. Assume compromise: they were committed in a repository.
2. **Purge history** (`git filter-repo` / BFG) as a deliberate, separate operation. History
   rewriting changes every commit hash and affects every worktree and clone.
3. **Redeploy** the dashboard after rotation so no service is still using a burned credential.
