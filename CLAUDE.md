# jarvis-trader — project memory

AI-powered futures & options trading engine for Matt Morrison.
Capital $10K total, $5K/instrument (MCL + MNQ). Paper mode on IB Gateway port 4002.

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
- Dashboard badge variants (strict): `"bull" | "bear" | "warn" | "info" | "neutral"`.
- No bare `await fetch(...)` in `dashboard/` — use `fetchEngine` / `postEngine` from `dashboard/lib/api.ts`.
- Engine restart: `.\restart_engine.ps1`. Never use `--reload` (causes duplicate IB connections).
- Live IB Gateway port 4001 is permanently blocked — paper only (port 4002, account DUP662235).
- Any change to `engine/config.py`, `engine/risk/`, or kill-switch code requires `[safety-review]` PR tag.
- `LIVE_TRADING_ENABLED = False` and `REQUIRE_HUMAN_APPROVAL = True` are invariants. Kill switch: -2% daily P&L / -10% drawdown. Hardcoded, no LLM route.
- API auth header: `X-API-Key: xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc` (from `engine/.env`). Port 8010.

## Dev quick-start

```bash
# Engine (http://localhost:8010)
cd engine && .venv/Scripts/activate && python main.py

# Dashboard (http://localhost:3010)
cd dashboard && pnpm install && pnpm dev

# Tests
cd engine && .venv/Scripts/python -m pytest tests/ -m "not slow"
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
