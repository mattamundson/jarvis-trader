---
description: Query and trigger the Obsidian second-brain vault jobs (status, synthesis brief, contradiction check, wikilink lint) via the engine's /vault API. Read-only by default; --run triggers a fresh job.
allowed-tools: Bash(curl:*), Read
argument-hint: "[status|brief|contradictions|lint] [--run]"
---

# Vault

**Inputs**: $ARGUMENTS

Parse `[action] [--run]`. Default action = `status`. Valid actions: `status`, `brief`,
`contradictions`, `lint`. Refuse any other action.

## Pre-flight

```bash
curl -s http://localhost:8010/health
```

- Engine down → STOP, print "engine down, vault query blocked".

## Run

```bash
API_KEY="${JARVIS_API_KEY}"
```

**`status`** (default — always read-only):

```bash
curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/vault/status
```

**`brief` / `contradictions` / `lint`** without `--run` — read the latest report:

```bash
curl -s -H "X-API-Key: $API_KEY" http://localhost:8010/vault/<action>/latest
```

A `404` means no report exists yet — say so; do not treat it as an error.

**`brief` / `contradictions` / `lint`** with `--run` — trigger a fresh job:

```bash
curl -s -X POST -H "X-API-Key: $API_KEY" http://localhost:8010/vault/<action>/run
```

A `409` means the job is disabled — report which `ENABLE_VAULT_*` flag to set in
`engine/.env` (the 409 detail names it). Do NOT attempt to edit `engine/.env` yourself.

## Report

```
## Vault — <action>

# for status:
- Root: <vault_root>
- Notes: 00-Inbox <n> | 01-Sources <n> | 02-Theses <n> | 03-Projects <n> | 04-Engine <n>
- Latest: brief <date|none> | lint <date|none> | contradictions <date|none>
- Armed: <list of ENABLE_VAULT_* flags that are true>

# for a report read/run:
- Result: <written path | latest report summary | 404 none yet | 409 disabled: set FLAG>
```

## Constraints

- This command never edits the vault by hand and never edits `engine/.env`. It only
  reads `/vault/*` and POSTs the gated `/run` endpoints, which the engine guards behind
  the same `ENABLE_VAULT_*` flags the cron jobs honour.
- The vault jobs never touch the order path, safety layer, or kill switch.

## Why this exists

The overnight vault automations (synthesis 06:00, lint 06:30, contradiction 07:00) only
ran on PM2 cron. This wraps the `/vault` router so a session can check vault state and
trigger a job on demand without remembering the API key, endpoint shapes, or flag names.
Full operator guide: `docs/runbooks/VAULT_AUTOMATION.md`.
