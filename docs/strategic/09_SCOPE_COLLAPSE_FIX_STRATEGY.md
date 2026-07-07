# 09 — Scope-Collapse Fix Strategy

**Status:** Active | **Owner:** Matt | **Created:** 2026-07-06
**Branch:** `claude/scope-collapse-fix-strategy-qdutz5`

> This document exists because every session on the "make it all work" ask ends at
> 5/10 and stops. This is the diagnosis of *why*, the sequenced fix plan, and the
> reusable machinery to drive each system to a verifiable green — one at a time.

---

## 1. Root-cause diagnosis (one sentence)

**Nothing is broken. Everything is wired but dead-configured.** Across all seven
"doesn't work" systems, the code exists, is registered, and has tests. What is
missing is the last non-code wire: an empty env var, a config default pointing at
forbidden symbols, three paths that disagree, a scheduler that deletes itself
weekly, a TTY prompt that blocks headless runs.

### Why sessions collapse to "small enhancements"

An agent greps, finds working code, "improves" it, and declares victory — because
the break was never *in the code*. It was in the config wire nobody set. Result:
you pay agents to polish engines whose fuel line isn't connected. The fix is not
more code; it is **connecting wires and verifying against a pass/fail spec**.

This was verified 2026-07-06 by four read-only diagnostic agents against the live
tree (dashboards / strategies+pipeline / autonomy+self-prompting / integrations).

---

## 2. Per-system evidence

| System | Real status | The actual blocker (file:line) |
|---|---|---|
| **JARVIS dashboard** | Wired, ~48 routes, builds | Vercel proxy never sent the ngrok headers `DEPLOY_VERCEL.md` requires → every engine call 401s / gets HTML splash. `app/api/engine/[...path]/route.ts` set only `X-API-Key`. **FIXED in this branch** (see §5). |
| **amo-arbitrage** | Not in this repo | External Railway service (`app/api/amo/[...path]/route.ts:16`), reportedly up. Only a read-only Trust-Pane column lives here. Nothing to fix in-repo. |
| **Trading strategies** | Pipeline fully wired to paper-exec | Default `FUTURES_WATCHLIST=MCL,MNQ,MES` but `DO_NOT_TRADE={MCL,MNQ,M2K}` force-`NO_TRADE`s 2 of 3 (`backtest/signals.py:113,186`). Default LLM provider is **Ollama** (`main.py:779`) — no local model ⇒ analysts silently HOLD (`main.py:798`). |
| **Autonomous loop** | Real, persistent, wired at boot (`main.py:1726`) | `AUTONOMOUS_ACTIVE_SYMBOLS=MCL,MNQ` default (`scheduler/pipeline_autonomous.py:91`) — both `DO_NOT_TRADE`, so every tick no-ops. Running, doing nothing, by config. **Safety-gated change.** |
| **JARVIS self-prompting** | Payload + guardrails + `claude -p` self-invoke all exist | Only unattended driver is a cloud Routine hand-created in the web UI that **auto-expires after 7 days** (`docs/runbooks/OVERNIGHT_ROUTINE_RUNBOOK.md:42-45`). No repo code re-creates it. "Worked then stopped" = it deleted itself. |
| **CC ↔ Obsidian** | `/vault` router wired + tested (`main.py:2979`) | `JARVIS_VAULT_ROOT` empty → falls back to non-existent `~/my-vault`; all 4 vault jobs flag-gated OFF (`.env.example:254-271`). Lint job needs **no LLM** — cheapest first win. |
| **X bookmarks** | Discord-mediated path real + tested + scheduled | Writes to **three colliding paths**: `main.py:2181` hardcoded `C:\...` vs `deep_analyzer/vault.py:12` `~/my-vault` vs `$JARVIS_VAULT_ROOT`. The literal "export my bookmarks" playbook has **no code** (`phase1_inventory.py`/`jarvis_funnel` do not exist). |
| **Hermes** | Self-upgrade pipeline real | Blocked headless by interactive `input("Apply? [y/N]")` gate (`engine/discord/hermes_upgrade/applier.py:164`); external WSL runtime, not reachable from cloud sessions. |

**Force multiplier:** unifying the three vault paths onto one root fixes **Obsidian
AND X-bookmarks** at once.

---

## 3. The operating principle (how to not collapse again)

Run this loop **once per system**. Do not batch systems.

1. **Pick one system.**
2. **Convert "doesn't work" into a concrete pass/fail acceptance spec** (§7 template).
3. **Diagnose-only pass** (no fixing) that reproduces the real failure and grades
   current state against the spec.
4. **Fix-to-green pass**, one criterion at a time, each verified before the next.
5. **Wire the autonomy layer LAST**, after the leaf systems are known-good. A loop
   whose job is to operate broken systems only amplifies the breakage.

One system green tonight beats seven at 6/10 — and it validates the workflow so the
next six go faster.

---

## 4. Sequenced fix plan

### 4a. Repo changes (doable + verifiable in a cloud session)

| # | Fix | Verify | Systems unblocked |
|---|---|---|---|
| F1 | **Dashboard proxy headers + env-var reconciliation** | `tsc --noEmit`, then live site after redeploy | JARVIS dashboard — **DONE, §5** |
| F2 | **Vault path unification** — route the 3 duplicated `~/my-vault` defaults (`deep_analyzer/vault.py`, `deep_analyzer/digest.py`) + the hardcoded `C:\...` in `main.py` through the canonical `vault.paths.vault_root()` so all honour `JARVIS_VAULT_ROOT` | standalone behavioral run + `test_vault_root_unification.py` | Obsidian + X-bookmarks — **DONE, §5.2** |
| F3 | **Hermes headless approval** — "`--yes` bypass" REJECTED as unsafe; fixed the real bug instead (EOF→terminal-skip now defers to retryable) | standalone run + `test_hermes_headless_defer.py` | Hermes — **DONE, §5.3** |
| F4 | **Doc/config reconciliation** — fix stale `markets/orchestrator.py` → `orchestrator/multi_market.py` in the live pointer docs | grep + `ls` | correctness/expectations — **DONE, §5.4** |
| F5 | **Numeric-accuracy unit tests** — lock the dashboard's pure P&L/win-rate/PF/drawdown/Sharpe derivations (`lib/honestTrades.ts`, `honestMetrics.ts`) to hand-computed values | `pnpm run test:unit` | trustworthy numbers — **DONE (beachhead), §5.1** |

### 4b. On-box steps (need your Windows/WSL runtime — exact commands provided)

- **Obsidian first green (no LLM):** set `JARVIS_VAULT_ROOT=<real folder>` and
  `ENABLE_VAULT_LINT=1` in `engine/.env` → `POST /vault/lint/run` →
  read `00-Inbox/lint-<date>.md` back. `GET /vault/status` confirms folder counts.
- **Strategies:** start Ollama (`OLLAMA_BASE_URL`) or set `ANTHROPIC_API_KEY` +
  `JARVIS_LLM_PROVIDER` so analysts stop silently HOLDing.
- **Durable overnight trigger:** replace the self-expiring cloud Routine with a
  persistent trigger (GitHub Action cron or a self-renewing Routine) so
  self-prompting survives past 7 days.

### 4c. Safety-gated (never touched without explicit OK + `[safety-review]` tag)

- Changing `AUTONOMOUS_ACTIVE_SYMBOLS` from `MCL,MNQ` to `MES,MGC` — this makes an
  inert loop start *proposing trades*. Requires Tier-3 confirmation.
- Anything in `engine/risk/`, `engine/config.py` safety params, kill-switch code.

---

## 5. What this branch already fixed (F1)

**Dashboard engine proxy — `dashboard/app/api/engine/[...path]/route.ts`:**
- Added `Authorization: Basic base64(ENGINE_TUNNEL_BASIC_AUTH)` — injected
  server-side only, so the credential never enters the browser bundle. Guarded on
  the env var being present (absent for local dev).
- Added `ngrok-skip-browser-warning: true` so the free-tier ngrok interstitial is
  skipped and the engine returns JSON, not an HTML splash.
- `dashboard/.env.example` rewritten to document the **server-side proxy vars**
  (`ENGINE_INTERNAL_URL`, `ENGINE_API_KEY`, `ENGINE_TUNNEL_BASIC_AUTH`) that the
  proxy actually reads — previously it documented only `NEXT_PUBLIC_*`, so setting
  the documented vars alone left the proxy on the dead `localhost:8010` fallback.

**Verification status (be precise — see CLAUDE.md "Verification discipline"):**
- **Behavior-verified (cloud):** header logic extracted to `lib/engineProxyHeaders.ts`
  and exercised by `tests/engineProxyHeaders.node.test.ts` (`pnpm run test:unit`, 6/6
  pass) — asserts `Authorization: Basic base64(user:pass)` is emitted from
  `ENGINE_TUNNEL_BASIC_AUTH`, `ngrok-skip-browser-warning: true` is always set, and
  Authorization is omitted in local dev. `tsc --noEmit` → exit 0.
- **UNVERIFIED — needs the box:** the live tunnel round-trip. A green Vercel deploy
  proves it *compiles/ships*, NOT that it works. Nobody has yet observed the deployed
  site return live JSON through the tunnel.

**Acceptance criterion (on-box, to actually close F1):** with the three Vercel env
vars set and the ngrok service up, a browser network trace of
`https://jarvis-trader-plum.vercel.app/api/engine/health` returns JSON `200` (not a
`401` or ngrok HTML), and a data page renders real numbers cross-checked against the
engine's own `/health` and `/portfolio` values — not just "not offline". Until that is
observed, F1 is **shipped but not closed**.

---

## 5.1. Numeric-accuracy beachhead (F5 — landed)

A trading dashboard's job is *correct numbers*; a confidently-wrong P&L is worse
than an offline page. The honest-record derivations (`lib/honestTrades.ts`,
`lib/honestMetrics.ts`) — which exist precisely because raw engine endpoints
over-count re-logged winners (fabricated +$3,899 / PF 2.95 vs deduped −$8,188 /
PF 0.66) — had **zero** test coverage.

Landed `dashboard/tests/honestNumbers.node.test.ts` (12 assertions,
`pnpm run test:unit`, green): `bySymbolStats` money math incl. the breakeven
win/loss boundary, `equityCurve` + `maxDrawdownPct` (drawdown is kill-switch
adjacent), `perTradeSharpe` incl. null guards, `dailyPnl` TZ-independent
invariants, and `summarizeRealized` dedup clamp. Plus test-infra: a `@/` alias
resolve hook so the Node runner can load aliased modules.

**Still a known gap (do not overclaim):** this is unit-level verification of the
pure transforms. There is still **no end-to-end numeric test** (engine → proxy →
render) proving the deployed dashboard shows the same number the engine holds —
that needs the live box and is the deeper work.

## 5.2. Vault path unification (F2 — landed)

The `~/my-vault` default was duplicated in three writers, none honouring
`JARVIS_VAULT_ROOT`: `deep_analyzer/vault.py` (X-post/bookmark pages),
`deep_analyzer/digest.py` (daily digest), and a hardcoded
`C:\Users\mattm\second-brain\wiki\discord-bookmarks` in `main.py`. All three now
fall back to the canonical `vault.paths.vault_root()`, so a single
`JARVIS_VAULT_ROOT` moves every writer together.

**Verification (per rung):**
- `deep_analyzer/vault.py`: **ran-and-observed** — with `JARVIS_VAULT_ROOT` set, an
  `X_POST` note lands at `<root>/Discord-Feed/<date>/…` and NOT under `~/my-vault`
  (standalone check; mirrored as `tests/test_vault_root_unification.py`).
- `deep_analyzer/digest.py`: import-verified + `ruff` clean + source-confirmed it
  falls back to `_vault_root()` (identical proven pattern; `render()` not executed
  here — needs a sqlite fixture).
- `main.py`: `ruff` clean + inspection (uses the tested `vault_root()`); not
  importable in this sandbox (pulls `httpx`).
- **UNVERIFIED — needs the box:** the full engine pytest suite
  (`test_vault_router` etc.) can't run here — `conftest.py` imports httpx-heavy
  agents. Run `cd engine && .venv/Scripts/python -m pytest tests/test_vault_root_unification.py tests/test_vault_*.py -v` on the box to close it.

**Open design decision (deliberately NOT silently made):** all writers now share
one *root*, but keep their existing *subfolders* (`Discord-Feed/`, `Daily/`,
`discord-bookmarks/`) — none of which are the numbered taxonomy folders
(`00-Inbox`…`04-Engine`) that the `/vault` lint/synthesis jobs scan. So bookmarks
are co-located but not yet swept by the vault jobs. Whether to move them into a
scanned taxonomy folder is a product choice for Matt, not a path bug.

## 5.3. Hermes headless approval (F3 — landed)

The diagnosis proposed a `--yes` flag to bypass the `input()` gate at
`applier.py:164`. **Rejected on closer read** — it would remove a deliberate
human-approval gate:

- A scoped headless path ALREADY exists: `--auto-approve-low-risk` auto-applies
  only `tier_1 + low_risk` entries (`applier.py:218`); everything riskier still
  requires a human. A blanket `--yes` would auto-apply tier_2/tier_3 and
  high-risk Hermes config/cron/soul patches unattended.
- **The real bug** is separate and worth fixing: on a headless run (no TTY),
  `except EOFError: ans = "n"` (`applier.py:165`) returns `notes="User skipped"`,
  which `apply_many` writes as the **terminal** `skipped` state
  (`applier.py:265`; terminal per `models.applicable_or_pending` = only
  `pending`/`failed` retry). So a scheduled scan permanently opts-out every
  non-low-risk entry — a later interactive run never sees them again.

**The fix shipped:** distinguish EOFError (no TTY) from an explicit user "n". On
EOF, `apply_one` now returns a *deferred* `ApplyResult` (`deferred=True`,
`models.py`) and `apply_many` leaves the entry in its retryable state
(`pending`/`failed`) and does not touch the applied-log — instead of writing the
terminal `skipped`. The human gate is untouched: non-auto-approvable entries
still require a person; they just wait instead of being destroyed.

**Verification:** `apply_one`/`apply_many` driven directly (applier stubbed,
`input` raising EOFError) — deferred entry stays `pending`, no applied-log write,
and an explicit `n` still terminally skips (regression preserved). ran-and-observed
here; mirrored as `tests/test_hermes_headless_defer.py` for the engine suite;
`ruff` clean. Operationally, the scheduled scan should still run with
`--auto-approve-low-risk` so tier_1+low_risk entries auto-apply while the rest defer.

## 5.4. Doc/config reconciliation (F4 — landed)

`engine/markets/orchestrator.py` does not exist (verified `ls`); the real
multi-market orchestrator is `engine/orchestrator/multi_market.py`. Fixed the
stale pointer in the live context docs: `engine/CLAUDE.md`,
`docs/CURRENT_STATE.md`, `.claude/imports/key-files.md`. Left untouched: dated
reports and session-log archives (point-in-time snapshots — correcting them
rewrites history) and `.claude/skills/jarvis-trader/RALPH.md:73` (already hedged
"or equivalent"; skill narrative, not a pointer). Vault + tunnel env vars were
already documented (root `.env.example:250+`, `dashboard/.env.example`).

## 6. Next-up recommendation

After F1, do **F2 (vault path unification)** next: it is repo-resident, verifiable
against existing tests, and unblocks two systems at once. Then the Obsidian on-box
lint round-trip (§4b) is the first end-to-end green you can *see* — no LLM, no
external service, ~2 minutes.

---

## 7. Reusable machinery — the two-pass prompts

### Pass 1 — Diagnostic (read-only, no fixes)

```
# DIAGNOSTIC PASS — <SYSTEM> — READ-ONLY
Diagnose why <SYSTEM> does not work. DIAGNOSIS ONLY — zero code changes.
Only file you may write is ./_diag_<SYSTEM>.md.

STEP 1 — Acceptance spec: read the code + its goals doc; propose 3-7 concrete,
testable pass/fail criteria (a command or observable result, not a vibe). I approve.

STEP 2 — Reproduce with read-only sub-agents (no writes, no recursion):
 - Wiring agent: is it even wired? routes defined-but-not-registered, services
   written-but-never-called, env/config never set, jobs never scheduled. CHECK FIRST.
 - Runtime agent: actually run/trigger it; capture the REAL error/stack/blank output;
   grade each criterion PASS/FAIL/BLOCKED with literal error text.
 - Dependency/config agent: missing pkgs, wrong versions, absent env vars (record KEY
   name only, never secret values), stale config.
 - Integration-boundary agent (only if it spans a boundary): verify each side
   independently; name which side breaks.

STEP 3 — Write ./_diag_<SYSTEM>.md: the spec; per-criterion status + exact evidence;
ranked root-cause hypotheses tied to evidence, distinguishing never-wired vs buggy vs
config; the single next action per FAIL; and a separate list of out-of-scope
enhancements you noticed (list only — do not build). STOP. Wait for spec approval.
```

### Pass 2 — Fix to green (after spec approval)

```
# FIX PASS — <SYSTEM> — DRIVE TO GREEN
Work from ./_diag_<SYSTEM>.md and the approved spec. Goal: every criterion PASSES,
shown with real output.

RULES: single-threaded (sub-agents only for read checks, never writing code). Fix ONE
criterion to green at a time; run the verification and paste passing output before the
next. No new features/enhancements — log adjacent work to ./_backlog_<SYSTEM>.md and
keep going. Preserve working behavior; follow existing conventions. No placeholder
code. If a fix needs a value only I have (env var/path/key), stop and ask for that one
thing. Two real options → present both + the splitting fact; don't pick unilaterally.

SEQUENCE: restate spec as checklist → order fixes by dependency (wiring/config before
logic) → per criterion: change, verify, show passing output, check box → when all
green, run ALL once more top-to-bottom and show the full passing run. Do NOT touch any
autonomy/loop layer on top of this system — leaf to known-good first.
```

---

*Companion to `docs/strategic/README.md`. Update §5/§6 as each fix lands.*
