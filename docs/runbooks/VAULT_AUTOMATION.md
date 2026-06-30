# JARVIS TRADER — Vault Automation (Obsidian Second Brain)

> Overnight Claude-over-vault jobs that synthesise, lint, reconcile, and back up
> the Obsidian second-brain vault. Adapted from DamiDefi's "9 Things My Obsidian
> Vault Does While I Sleep" and the Moysei/Karpathy 10-step second-brain pattern.

**Status**: Code shipped; all jobs default **OFF** until armed. **Python**: 3.12 | **venv**: engine/.venv/

---

## Overview

The vault is a plain-markdown Obsidian knowledge base outside this repo (it is the
trader's, not the engine's). The engine reads and writes it but never owns it. Five
taxonomy folders, numbered to keep Obsidian's file-explorer order stable:

| Folder | Holds |
|--------|-------|
| `00-Inbox` | Generated automation output — briefs, lint reports, contradiction scans |
| `01-Sources` | External material — Discord/X analyses, papers, captures |
| `02-Theses` | Documented trading positions / hypotheses |
| `03-Projects` | Active research and writing |
| `04-Engine` | Pipeline outputs, backtest results |

Taxonomy + read/write helpers: `engine/vault/paths.py`. The vault root resolves
from `JARVIS_VAULT_ROOT` (env), defaulting to `~/my-vault`, read fresh on every call.

## The jobs

| Job | When (CT) | Reads | Writes | Arming flag | PM2 app |
|-----|-----------|-------|--------|-------------|---------|
| Synthesis brief | 06:00 | last 7d of `00`–`03` | `00-Inbox/brief-DATE.md` | `ENABLE_VAULT_SYNTHESIS` | `jarvis-vault-synthesis` |
| Wikilink lint | 06:30 | all notes (no LLM) | `00-Inbox/lint-DATE.md` | `ENABLE_VAULT_LINT` | `jarvis-vault-lint` |
| Contradiction check | 07:00 | `02-Theses` + last 30d `01-Sources` | `00-Inbox/contradictions-DATE.md` | `ENABLE_VAULT_CONTRADICTION` | `jarvis-vault-contradiction` |
| GitHub backup | 00:00 | the whole vault | commit + push to the vault's own remote | `ENABLE_VAULT_BACKUP` | `jarvis-vault-backup` |
| Bookmark render | 03:00 | `discord_bookmarks` SQLite | `…/wiki/discord-bookmarks/` | (always on) | lifespan scheduler in `main.py` |

- **Synthesis** (`engine/vault/synthesis.py::run_synthesis_brief`) — "synthesise, don't
  summarise": connections, pattern, contradiction, best capture.
- **Lint** (`engine/vault/lint.py::run_lint`) — pure-filesystem structural integrity:
  broken `[[wikilinks]]` and orphan notes. No LLM, no network, no spend.
- **Contradiction** (`engine/vault/synthesis.py::run_contradiction_check`) — adversarial
  scan of theses against recent sources; surfaces conflict, not agreement.
- **Backup** (`engine/scripts/backup_vault_to_github.py`) — off-device version history.

Every job is gated by its flag, read fresh at run time, and degrades gracefully
(no notes / LLM down → logs and exits 0). None touches the order path or any safety
file.

## How to arm

1. Point the engine at the vault and set the flags you want in `engine/.env`:

   ```dotenv
   JARVIS_VAULT_ROOT=/path/to/your/second-brain   # or C:/Users/<you>/second-brain on Windows
   ENABLE_VAULT_SYNTHESIS=1
   ENABLE_VAULT_LINT=1
   ENABLE_VAULT_CONTRADICTION=1
   # ENABLE_VAULT_BACKUP=1   # only after the one-time git setup below
   ```

   See `.env.example` for the full list (model + day-window overrides).

2. Reload the PM2 fleet so the cron jobs pick up the new env:

   ```bash
   pm2 reload engine/ecosystem.config.js
   pm2 ls | grep jarvis-vault   # confirm the four vault jobs are listed
   ```

3. (Backup only, one-time) make the vault its own git repo with a private remote:

   ```bash
   cd "$JARVIS_VAULT_ROOT" && git init && git remote add origin <private-repo-url>
   git config user.email <you> && git config user.name <you>
   ```

## On-demand (no waiting for cron)

The `/vault` API router and the `/vault` Claude Code command trigger and read the same
jobs without waiting for the overnight schedule. Both honour the SAME flags — a disabled
job returns **HTTP 409**, so the API cannot bypass a gate that is intentionally off.

```bash
API_KEY="${JARVIS_API_KEY}"
curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/vault/status
curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/vault/lint/latest
curl -s -X POST -H "X-API-Key: $API_KEY" http://localhost:8010/vault/lint/run
```

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/vault/status` | GET | Vault root, per-folder note counts, latest report dates, flag states |
| `/vault/{brief,contradictions,lint}/latest` | GET | Most recent report body (404 if none) |
| `/vault/{brief,contradictions,lint}/run` | POST | Run now (409 unless the matching flag is armed) |

In a Claude Code session: `/vault status`, `/vault lint`, or `/vault brief --run`. See
`.claude/skills/jarvis-vault/SKILL.md`.

## Verify it worked

```bash
# After arming + reload, force a lint run and read it back:
cd engine && ENABLE_VAULT_LINT=1 .venv/Scripts/python scripts/vault_lint.py
ls "$JARVIS_VAULT_ROOT/00-Inbox/" | grep lint-

# Or via the API:
curl -s -X POST -H "X-API-Key: $JARVIS_API_KEY" http://localhost:8010/vault/lint/run
```

A run that produces nothing (empty vault, missing theses, LLM unreachable) is logged and
exits 0 — that is expected before the vault is populated, not an error.

## Tests

- `engine/tests/test_vault_paths.py` — taxonomy + read/write helpers
- `engine/tests/test_vault_synthesis.py` — brief + contradiction (fake LLM client)
- `engine/tests/test_vault_lint.py` — broken-link + orphan detection
- `engine/tests/test_vault_router.py` — status / latest / armed-vs-409 run gating

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_vault_*.py -v
```
