# jarvis-trader — project memory

AI-powered futures & options trading engine for Matt Morrison.
Capital $10K total, $5K/instrument. Active paper instrument: MES (Tier-3 auth 2026-05-24).
MCL, MNQ, M2K, and MGC are HALTED (`DO_NOT_TRADE_SYMBOLS`) — MGC joined 2026-07-31 after
the honest-data-drain DSR correction invalidated its 2026-05-24 gate-v2 PASS.
`engine/CLAUDE.md` "Active Instruments" is the authoritative status table. Paper mode on
IB Gateway port 4002, account DUR375089 (confirmed live 2026-08-10 via `IB_ACCOUNT_ID` in
`engine/.env` and IB position/execution queries — corrects a stale `DUP662235` reference).

## Read first (in order)

1. `docs/CURRENT_STATE.md` — latest P0/P1/P2 status
2. `docs/JARVIS_TRADER_UNIFIED_CANON.md` — canonical architecture
3. `docs/runbooks/` — operational playbooks
4. `engine/config.py` — hardcoded safety limits (DO NOT modify without `[safety-review]` PR tag)
5. `docs/troubleshooting.md` — engine/OpenClaw/WhatsApp/Bun/port-8010 incidents

## Non-negotiable rules

- `.env` files NEVER committed. Real keys live in `engine/.env` (gitignored).
- `pnpm` for all Node. System `npm` is broken.
- Python: `engine/.venv/Scripts/python` only. Never system Python 3.14 or Store Python.
- TS check: `./node_modules/.bin/tsc --noEmit` (not `npx tsc`).
- Dashboard badge variants (strict): `"bull" | "bear" | "warn" | "info" | "neutral" | "live" | "static"` (`live`/`static` are Trust-Pane data-provenance badges).
- No bare `await fetch(...)` in `dashboard/` — use `fetchEngine` / `postEngine` from `dashboard/lib/api.ts`.
- Engine restart: `.\restart_engine.ps1`. Never use `--reload` (causes duplicate IB connections).
- Live IB Gateway port 4001 is permanently blocked — paper only (port 4002, account DUR375089).
- Any change to `engine/config.py`, `engine/risk/`, or kill-switch code requires `[safety-review]` PR tag.
- `LIVE_TRADING_ENABLED = False` and `REQUIRE_HUMAN_APPROVAL = True` are invariants. Kill switch: -6% daily P&L / -20% drawdown — both are the current `MAX_DAILY_LOSS_PCT` (0.06) and `MAX_DRAWDOWN_PCT` (0.20) `config.py` code defaults, reconciled to `engine/.env` live truth on 2026-06-25 (that file remains the source of truth for the live value). The kill-switch logic is hardcoded, no LLM route.
- API auth header: `X-API-Key: <current value in `engine/.env`>` (value rotates — read at use time, do not hardcode here). Port 8010.

## Verification discipline (non-negotiable)

**Incident 2026-07-06 (PR #280):** an agent added the missing ngrok tunnel-auth headers
to the dashboard engine proxy, ran `tsc --noEmit` (exit 0), watched the Vercel deploy go
"Ready", and reported the fix "verified, and shipped" — then told Matt his env vars would
"close" it. **None of that verified the fix.** `tsc` proves the code *type-checks*; a green
build/deploy proves it *compiles and ships*. Neither exercises the proxy, so neither
confirms the headers are actually injected or that the tunnel returns JSON. Compiling is
not behaving. The agent conflated "it builds" with "it works," and handed the real
verification to the user while calling it done. These rules exist so that never repeats.

- **"Verified / works / done / closed / fixed" is a claim about observed runtime behavior,
  not about compilation.** Never use those words unless you *ran the actual path and observed
  the result*. `tsc --noEmit`, `pnpm run build`, `ruff`, a green Vercel/CI deploy, and "the
  import succeeded" are **compilation/lint signals only** — report them as exactly that, never
  as proof the feature works.
- **State the verification level explicitly.** Every "done" claim names what you actually did:
  `type-checks only` < `unit-tested` < `ran and observed output` < `end-to-end through the
  real engine/broker`. If you only reached a lower rung, say so in the same sentence.
- **If you cannot verify from this environment, say "UNVERIFIED — needs <X>".** Do not imply
  completion and outsource the check to Matt. Hand him the exact one-command check and label
  the item open until someone observes it pass. Handing over the verification ≠ doing it.
- **Numeric accuracy is a first-class verification target, not a side effect.** This is a
  trading system: a dashboard or endpoint that renders a *confidently wrong* number (P&L,
  position size, price, signal confidence, drawdown, kill-switch distance) is worse than one
  that's visibly offline — Matt trades on the number, not the uptime. "The page loaded" and
  "the JSON parsed" say nothing about whether the value is correct.
  - Never present a number as correct without checking it against its source of truth
    (engine endpoint ↔ DB ↔ known/hand-computed value). No "looks right."
  - A change that touches how any number is computed, aggregated, rounded, unit-converted, or
    labeled requires a value-level check with known inputs → expected output, not just a build.
  - Prefer the engine/DB as the scoreboard over the rendered UI; cross-check engine↔dashboard
    for the same metric when both display it. Round-trip drift = a bug, not cosmetic.
  - There is currently **no end-to-end numeric-accuracy test** (engine → proxy → render). Treat
    that as a known gap: do not assume displayed numbers are validated, and flag it when a task
    depends on them.
- **A rule you write for yourself, you follow in the same session.** Do not add a
  "verify behavior" rule and then leave the triggering change behavior-unverified.

## Dev quick-start

```bash
# Engine (http://localhost:8010)
cd engine && .venv/Scripts/activate && python main.py

# Dashboard (http://localhost:3010)
cd dashboard && pnpm install && pnpm dev

# Tests (restate `not manual` — a CLI -m overrides pyproject's default and
# re-collects the IB-Gateway e2e tests, which hang when a gateway is reachable)
cd engine && .venv/Scripts/python -m pytest tests/ -m "not slow and not manual"
cd dashboard && pnpm run build
```

## Subagents available

Use `/jarvis-*` commands or invoke subagents by name from `.claude/agents/`:

- `pipeline-debugger` — debate scoring, signal aggregation, IC weights
- `backtest-runner` — WFE / PF / Sharpe validation + Monte Carlo
- `safety-reviewer` — kill switch, stop-loss direction invariants, safety layer

## Imports

@.claude/rules/safety.md
@.claude/rules/testing.md
@.claude/rules/commits.md
@.claude/rules/meta-discipline.md

---
*Last updated 2026-04-16 — replaces prior stale Paperclip memory.*
