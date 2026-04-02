# JARVIS TRADER

> AI-powered futures & options trading system — paper trading validation phase

## Project Overview

- **Engine**: FastAPI, Python 3.12, port **8010** — `engine/` (80+ routes, 24 routers)
- **Dashboard**: Next.js 15, TypeScript, port **3010** — `dashboard/`
- **Strategy**: STC oscillator (OS=15, OB=83) + ATR stops (0.70x) + 5-layer regime filter
- **Status**: Hardening phase — multi-market framework complete, paper trading prep
- **Architecture**: 5-stage LLM pipeline + learning system + multi-market orchestrator + 10 agents

## Session Start

**ALWAYS invoke `/jarvis-trader`** (NOT `/jarvis-v2`) for sessions in this directory.
`/jarvis-v2` is for Greenfield Metal Sales — unrelated project.

**Skill Pack** — A complete Claude Code skill pack lives at `.claude/skills/jarvis-trader/`.
Load `SKILL.md` from that directory at the start of any session for full codebase orientation,
task classification, playbook routing, and the acceptance checklist.

## Critical Safety Rules

> See `.claude/rules/safety.md` for full details.

- `LIVE_TRADING_ENABLED = False` — paper mode until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — always
- Safety layer is **hardcoded Python** — never use LLM for safety decisions
- Kill switch: -2% daily loss, -10% drawdown — non-negotiable
- No IB Gateway orders without Tier 3 confirmation

## Architecture

**Core Pipeline** (5-stage LLM orchestration):
- Stage 1: Parallel analysis (TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalistAgent)
- Stage 2: Debate (BullResearcher, BearResearcher, DebateOrchestrator)
- Stage 3: Decision (TraderAgent)
- Stage 4: Risk (RiskManagerAgent — full VETO power)
- Stage 5: Approval (FundManagerAgent)

**Multi-Market Framework**: `markets/orchestrator.py` manages futures, options, crypto with pluggable modules

**Learning System**: `learning/` (4 modules) — events, feedback, patterns, recommendations

**Infrastructure**:
- Risk params: `engine/config.py` → `TradingConfig`
- Safety enforcement: `engine/risk/safety_layer.py` (hardcoded, never LLM)
- Signal logic: `engine/backtest/signals.py` (canonical — Tier 3 to change)

## Key Files

| File | Purpose |
|------|---------|
| `engine/main.py` | FastAPI app, 421 lines, routes dispatched to 24 routers |
| `engine/routers/` | 24 router files organizing 80+ API endpoints |
| `engine/config.py` | `TradingConfig` — all risk parameters |
| `engine/agents/pipeline.py` | 5-stage trading pipeline orchestrator |
| `engine/risk/safety_layer.py` | Kill switch, hard limits, order validation |
| `engine/backtest/signals.py` | STC signal logic — CANONICAL parameter source |
| `engine/markets/orchestrator.py` | Multi-market orchestrator (futures, options, crypto) |
| `engine/learning/` | Learning system (events, feedback, patterns, recommendations) |
| `engine/hooks/` | React hooks module (state + market data) |
| `dashboard/lib/api.ts` | `fetchEngine`/`postEngine` — ALL dashboard API calls |
| `dashboard/app/layout.tsx` | Root Next.js layout |

## Coding Standards

> See `.claude/rules/coding-style.md` for full details.

- Python: async with graceful fallback, Pydantic v2, ruff-clean
- TypeScript: Next.js App Router, `"use client"` only when needed, Tailwind
- **All dashboard fetch via `fetchEngine`/`postEngine`** — never hardcode `localhost:8010`
- File size: 400 lines typical, 800 max

## Environment & Commands

```bash
# Engine (Python venv)
cd engine && .venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Dashboard
cd dashboard && pnpm dev

# Both (Windows)
start_jarvis.bat

# Tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Dashboard build check
cd dashboard && pnpm run build

# Secrets check
bash scripts/hooks/check-secrets.sh
```

**Python venv**: `engine/.venv/` — always use `.venv/Scripts/python`, not system Python
**Package manager**: `pnpm` for all Node.js work — system npm is broken

## Validated Instruments

| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | APPROVED — paper trading active |
| MNQ | 1h | 0.57 | APPROVED — paper trading active |
| MGC | 1d | 0.14 | HALTED — overfit/small-sample |
| MES | 1h | 0.09 | DO NOT TRADE |

## Documentation Layout

```
docs/
├── architecture/    — Endpoints, WebSocket, API analysis
├── setup-guides/    — Postgres, Prometheus, FRED, MCP, API keys
├── runbooks/        — Paper trading, security remediation, daily routine
├── reports/         — Verification reports, test results, strategy summary
├── session-logs/    — Historical session logs
├── dashboards/      — HTML status dashboards
├── analysis/        — Deep-dive analysis files
└── archive/         — Superseded documents (kept for reference)
```

## Git & Security

> See `.claude/rules/git-workflow.md` for full details.

- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- **Never commit**: `.env`, credentials, API keys, `client_secret*.json`
- `pnpm run build` must pass before pushing

## gstack Skills

gstack v0.15.1.0 is vendored at `.claude/skills/gstack/`. 33 specialized engineering
skills are available. See `AGENTS.md` for the full skill → workflow map.

**First-time setup** (requires Bun v1.0+):
```bash
cd .claude/skills/gstack && ./setup
```

**Key skills for this project:**

| Skill | When |
|-------|------|
| `/review` | **Required** before any PR touching `engine/risk/safety_layer.py` |
| `/investigate` | Debug agent pipeline failures |
| `/qa` | Test dashboard at http://localhost:3010 with real browser |
| `/ship` | Full release workflow: tests → review → push → PR |
| `/cso` | OWASP + STRIDE security audit of FastAPI engine |
| `/benchmark` | Pipeline latency regression detection |
| `/office-hours` | Product reframe before designing new trading features |

**Skill routing:** When the user asks to "review", "QA", "ship", or "investigate",
proactively invoke the matching gstack skill. Skills read this CLAUDE.md for project
context — they are platform-agnostic by design.

**Browse binary:** `/qa` and `/browse` use a compiled Bun binary at
`.claude/skills/gstack/browse/dist/browse`. Run `./setup` to build it.
Dashboard QA target: `http://localhost:3010`. Engine API: `http://localhost:8010`.
