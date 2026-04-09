# JARVIS TRADER

> AI-powered futures & options trading system — paper trading validation phase

<!-- IMPORTANT: Keep this file under 150 lines. Verbose sections live in .claude/imports/ and docs/. -->

## Session Start

**ALWAYS invoke `/jarvis-trader`** (NOT `/jarvis-v2`) for sessions in this directory.

## Project Overview

- **Engine**: FastAPI, Python 3.12, port **8010** — `engine/` (90+ routes, 26 routers)
- **Dashboard**: Next.js 15, TypeScript, port **3010** — `dashboard/`
- **Strategy**: STC oscillator (OS=15, OB=83) + ATR stops (0.70x) + 5-layer regime filter
- **Status**: Hardening phase — multi-market framework complete, paper trading validation
- **Architecture**: 5-stage LLM pipeline + learning system + multi-market orchestrator + 10 agents

## Critical Safety Rules

> Full invariants: @.claude/rules/safety.md

- `LIVE_TRADING_ENABLED = False` — paper mode until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — always
- Safety layer is **hardcoded Python** — NEVER use LLM for safety decisions
- Kill switch: -2% daily loss, -10% drawdown — non-negotiable
- **engine/risk/safety_layer.py** and **engine/config.py** are Tier 3 files — require explicit confirmation

## Architecture

**Core Pipeline** (5-stage LLM orchestration):
- Stage 1: Parallel analysis (TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalistAgent)
- Stage 2: Debate (BullResearcher, BearResearcher, DebateOrchestrator)
- Stage 3: Decision (TraderAgent)
- Stage 4: Risk (RiskManagerAgent — full VETO power)
- Stage 5: Approval (FundManagerAgent)

**Multi-Market Framework**: `markets/orchestrator.py` — futures, options, crypto
**Learning System**: `learning/` — 4 modules (events, feedback, patterns, recommendations)

**Strategic docs:** `docs/strategic/README.md` — command-center index (brief, SWOT, risk register, execution spine).

See @.claude/imports/key-files.md for the full file purpose table.

## Environment & Commands

```bash
# Engine (no --reload — use restart_engine.ps1 after config changes)
cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010
.\restart_engine.ps1           # kills port 8010, restarts
.\restart_engine_admin.ps1     # if taskkill fails (UAC required)

# Dashboard
cd dashboard && pnpm dev

# Both (Windows)
start_jarvis.bat

# Tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Backtest
cd engine && .venv/Scripts/python -m backtest.run_backtest --symbol MES --interval 1h

# TypeScript check (NOT npx tsc)
cd dashboard && ./node_modules/.bin/tsc --noEmit

# Build check
cd dashboard && pnpm run build

# Secrets check
bash scripts/hooks/check-secrets.sh
```

**Python venv**: `engine/.venv/` — always `.venv/Scripts/python`, never system Python
**Package manager**: `pnpm` — system npm is broken

## Coding Standards

> Full standards: @.claude/rules/coding-style.md

- Python: async with graceful fallback, Pydantic v2, ruff-clean, 400 lines typical / 800 max
- TypeScript: Next.js App Router, `"use client"` only when needed, Tailwind
- **ALL dashboard API calls via `fetchEngine`/`postEngine`** — never hardcode `localhost:8010`
- Badge variants STRICT: `"bull" | "bear" | "warn" | "info" | "neutral"` — no others

## Validated Instruments & Capital

> @.claude/imports/validated-instruments.md

| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | APPROVED |
| MNQ | 1h | 0.57 | APPROVED |
| MGC | 1d | 0.14 | HALTED |
| MES | 1h | 0.09 | DO NOT TRADE |

Gates: PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%, Trades ≥ 60, Days ≥ 30

## Troubleshooting

**READ FIRST for any system issues**: `docs/troubleshooting.md`

Covers: OpenClaw WhatsApp failures, Twilio config, engine restart (elevated process), Bun Stop hook, port 8010 zombie processes.

Quick fix scripts:
- OpenClaw lockout: `wsl -d Ubuntu -e python3 /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/scripts/fix-openclaw-lockout.py`
- Engine restart blocked: kill oldest `python.exe` in Task Manager (Admin) → `.\restart_engine.ps1`

## Git & Security

> Full workflow: @.claude/rules/git-workflow.md

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- **Never commit**: `.env`, credentials, API keys, `client_secret*.json`
- `pnpm run build` must pass before pushing

## Custom Subagents

`.claude/agents/` defines 4 trading-specific subagents:

| Agent | Use For |
|-------|---------|
| `safety-reviewer` | Any PR touching risk/safety code (REQUIRED before merge) |
| `backtest-runner` | Running backtests and interpreting WFE results |
| `dashboard-qa` | Build verification and convention checks |
| `pipeline-debugger` | Diagnosing pipeline stage failures |

## gstack Skills

> @.claude/imports/gstack-skills.md

Key skills: `/review` (safety PRs), `/qa` (browser testing), `/ship` (release), `/investigate` (debug)

## Parallel Agents

> @.claude/imports/parallel-agents.md

Deploy up to 10 foreground agents. Use task manifest at `.claude/task-manifest.json` for atomic checkout. Reset before multi-agent session.
