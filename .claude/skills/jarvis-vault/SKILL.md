---
name: jarvis-vault
description: Operate the jarvis-trader Obsidian second-brain vault from a Claude Code session — understand the 5-folder taxonomy, read the overnight synthesis / lint / contradiction reports, and trigger them on demand via the /vault API. Use when the user says "check the vault", "run the synthesis brief", "lint the vault", "what's in 00-Inbox", "find vault notes on X", or before inventing code that the vault may already cover.
---

# jarvis-vault

The Obsidian second-brain vault is a plain-markdown knowledge base that lives OUTSIDE
this repo (it is the trader's, not the engine's). The engine reads and writes it but
never owns it. Overnight Claude-over-vault jobs file, lint, and reconcile it while the
trader sleeps — adapted from DamiDefi's "9 Things My Obsidian Vault Does While I Sleep"
and the Moysei/Karpathy 10-step second-brain pattern.

## Taxonomy (engine/vault/paths.py)

| Folder | Holds |
|--------|-------|
| `00-Inbox` | Generated automation output — briefs, lint reports, contradiction scans |
| `01-Sources` | External material — Discord/X analyses, papers, captures |
| `02-Theses` | Documented trading positions / hypotheses |
| `03-Projects` | Active research and writing |
| `04-Engine` | Pipeline outputs, backtest results |

Root resolves from `JARVIS_VAULT_ROOT` (env), default `~/my-vault`. **You never hand-edit
the vault from a session** — the jobs and the human curate it. You query and trigger.

## The jobs (all gated, default off)

| Job | Schedule | Output | Arming flag |
|-----|----------|--------|-------------|
| Synthesis brief | 06:00 CT | `00-Inbox/brief-DATE.md` | `ENABLE_VAULT_SYNTHESIS` |
| Wikilink lint (no LLM) | 06:30 CT | `00-Inbox/lint-DATE.md` | `ENABLE_VAULT_LINT` |
| Contradiction check | 07:00 CT | `00-Inbox/contradictions-DATE.md` | `ENABLE_VAULT_CONTRADICTION` |
| GitHub backup | 00:00 CT | push to vault's own remote | `ENABLE_VAULT_BACKUP` |

## How to use it from a session

Use the `/vault` command, or `curl` the router directly (engine on port 8010, auth header
`X-API-Key: $JARVIS_API_KEY`):

```bash
curl -s -H "X-API-Key: $JARVIS_API_KEY" http://localhost:8010/vault/status
curl -s -H "X-API-Key: $JARVIS_API_KEY" http://localhost:8010/vault/lint/latest
curl -s -X POST -H "X-API-Key: $JARVIS_API_KEY" http://localhost:8010/vault/brief/run
```

- `GET /vault/status` — vault root, per-folder note counts, latest report dates, flag states.
- `GET /vault/{brief,contradictions,lint}/latest` — most recent report body (404 if none yet).
- `POST /vault/{brief,contradictions,lint}/run` — run now. **409 means the job is disabled**;
  the response names the `ENABLE_VAULT_*` flag to set in `engine/.env`. Report it; don't edit
  `engine/.env` yourself.

## When to reach for the vault

- **Before inventing code** (pairs with `jarvis-search-discipline` Step 4): `/vault status`
  then read the relevant latest report instead of re-deriving research the vault may hold.
- **After a research session** the human captured into `01-Sources`: run the synthesis brief
  and the contradiction check to surface connections and conflicts.
- **When links rot**: run the lint pass to find broken `[[wikilinks]]` and orphan notes.

## Hard rules

- The vault jobs **never** touch the order path, safety layer (`engine/risk/`), or kill
  switch. This skill is read/curate only.
- Never bypass a disabled flag. A 409 is the system working as designed.
- Full operator guide: `docs/runbooks/VAULT_AUTOMATION.md`. Code: `engine/vault/`,
  `engine/routers/vault_router.py`.
