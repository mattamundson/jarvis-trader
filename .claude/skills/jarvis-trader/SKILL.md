---
name: jarvis-trader
description: >
  Operational skill for Claude Code sessions working in the JARVIS TRADER
  codebase — a FastAPI + Next.js AI-powered futures and options trading system.
  Covers task classification, navigation, pipeline understanding, safety rules,
  coding standards, and playbook routing for every work type.
version: 2.0.0
---

# JARVIS TRADER — Claude Code Skill

> AI-powered futures and options trading system.
> Engine: FastAPI / Python 3.12 on port **8010** (`engine/`)
> Dashboard: Next.js 15 / TypeScript on port **3010** (`dashboard/`)
> Status: Paper trading validation phase — `LIVE_TRADING_ENABLED = False`

---

## 1. Session Start Protocol

Every new session MUST begin with:

1. Read `CLAUDE.md` (project root) — master rules and key file index
2. Read `.claude/rules/safety.md` — non-negotiable trading safety invariants
3. Read `.claude/rules/coding-style.md` — Python + TypeScript standards
4. Read `.claude/rules/git-workflow.md` — commit format, secrets rules
5. Identify the task type (see Section 3) and load the matching playbook

---

## 2. Safety Invariants (Non-Negotiable)

These are **hardcoded in Python** and must NEVER be overridden by LLM reasoning.

| Invariant | Value |
|---|---|
| `LIVE_TRADING_ENABLED` | `False` — paper mode only until Phase 3 |
| `REQUIRE_HUMAN_APPROVAL` | `True` — every trade needs human review |
| Daily loss kill switch | -2% |
| Emergency drawdown halt | -10% from peak |
| Safety authority | `engine/risk/safety_layer.py` ONLY |
| IB Gateway | Tier 3 confirmation required; port 4001 permanently blocked |

**Never** modify `engine/risk/safety_layer.py` without Tier 3 confirmation and a code review.
**Never** use LLM output to make safety decisions.

---

## 3. Task Classification

Classify every incoming request before writing a single line:

| Task Type | Trigger Words | Load Playbook |
|---|---|---|
| `bugfix` | error, crash, broken, failing, exception | `playbooks/debug.md` |
| `feature` | add, build, create, implement, new | `playbooks/add-feature.md` |
| `refactor` | clean up, restructure, reorganize, simplify | `playbooks/refactor.md` |
| `test` | test, coverage, pytest, passing, CI | `playbooks/test.md` |
| `release` | ship, deploy, push, tag, version | `playbooks/release.md` |
| `docs` | document, explain, update docs, README | write docs inline |
| `investigation` | why, what's happening, trace, debug | `playbooks/debug.md` |

---

## 4. Codebase Navigation

### Fastest path to any area

| Goal | Start here |
|---|---|
| Understand routing | `engine/main.py` — imports all 24 routers |
| Find an endpoint | `engine/routers/<area>_router.py` |
| Understand the trade pipeline | `engine/agents/pipeline.py` |
| Change a risk parameter | `engine/config.py` → `TradingConfig` |
| Check safety enforcement | `engine/risk/safety_layer.py` |
| Change signal logic | `engine/backtest/signals.py` (CANONICAL) |
| Understand multi-market | `engine/markets/` directory |
| Understand learning system | `engine/learning/` directory |
| Dashboard API calls | `dashboard/lib/api.ts` → `fetchEngine` / `postEngine` |
| Dashboard pages | `dashboard/app/<page>/page.tsx` |
| Run tests | `engine/tests/` — 18 test files |

### Router → Endpoint prefix mapping

| Router file | Prefix / area |
|---|---|
| `health_router.py` | `/health`, `/status`, `/system/preflight` |
| `analysis_router.py` | `/analyze/*`, `/scan`, `/scheduler/*` |
| `pipeline_router.py` | `/run`, `/progress`, `/decisions/*` |
| `backtest_router.py` | `/backtest/*` |
| `safety_router.py` | `/halt`, `/resume`, `/status` |
| `market_router.py` | `/markets`, `/market/*`, `/prices/*` |
| `portfolio_router.py` | `/portfolio`, `/positions`, `/pnl`, `/targets` |
| `strategies_router.py` | `/strategy/*`, `/strategies/*` |
| `settings_router.py` | `/settings/risk` |
| `sentiment_router.py` | `/sentiment/*` |
| `macro_router.py` | `/macro/*` |
| `journal_router.py` | `/trades`, `/record`, `/journal` |
| `options_router.py` | `/chain/*`, `/greeks`, `/iv-rank/*` |
| `crypto_router.py` | `/crypto/*` |
| `paper_validation_router.py` | `/paper/*`, `/backtest/paper-status` |
| `watchlist_router.py` | `/watchlist/*` |
| `reports_router.py` | `/summary`, `/performance/*` |
| `webhook_router.py` | `/webhook/*` |
| `websocket_router.py` | `/ws/*` |
| `validation_router.py` | `/validation/*` |
| Notifications routes on `engine/main.py` | `/notifications/*` |
| `thinkscript_router.py` | `/thinkscript/*` |
| `decisions_router.py` | `/decisions/*` |
| `polymarket_router.py` | `/polymarket/*` |

---

## 5. The 5-Stage Trading Pipeline

Defined in `engine/agents/pipeline.py` — `TradingPipeline.analyze_and_decide()`.

```
Stage 1 — ANALYSIS (parallel)
  TechnicalAnalystAgent   ← engine/agents/technical_analyst.py
  NewsAnalystAgent        ← engine/agents/news_analyst.py
  SocialAnalystAgent      ← engine/agents/social_analyst.py
  FundamentalistAgent     ← engine/agents/fundamental_analyst.py

Stage 2 — DEBATE
  BullResearcherAgent     ← engine/agents/bull_researcher.py
  BearResearcherAgent     ← engine/agents/bear_researcher.py
  DebateOrchestrator      ← engine/agents/debate.py

Stage 3 — DECISION
  TraderAgent             ← engine/agents/trader.py  → TradeDecision

Stage 4 — RISK (VETO POWER)
  RiskManagerAgent        ← engine/agents/risk_manager.py  → RiskDecision

Stage 5 — APPROVAL
  FundManagerAgent        ← engine/agents/fund_manager.py  → FundDecision
```

All stages degrade gracefully — a failing analyst returns a neutral report; the pipeline continues. Never skip RiskManagerAgent or FundManagerAgent.

---

## 6. Validated Instruments

| Symbol | TF | WFE | Status |
|---|---|---|---|
| MCL | 1h | 0.82 | APPROVED — paper trading active |
| MNQ | 1h | 0.57 | APPROVED — paper trading active |
| MGC | 1d | 0.14 | HALTED — overfit / small sample |
| MES | 1h | 0.09 | DO NOT TRADE |

Signal parameters live in `engine/backtest/signals.py` → `INSTRUMENT_PARAMS`. This is the CANONICAL source — never duplicate these values elsewhere.

---

## 7. Coding Standards Quick Reference

### Python
- All external calls: `async` with fallback
- Pydantic v2: `model_config = ConfigDict(...)`, `model_validate()`
- ruff-clean: zero errors required
- File size: 400 lines typical, 800 max absolute
- Function size: 50 lines max
- Endpoints: always `try/except` → `HTTPException`
- Logging: `logging.getLogger(__name__)` — never `print()`

### TypeScript
- Default to Server Components; `"use client"` only for browser APIs / interactivity
- **All engine calls via `fetchEngine` / `postEngine`** — never hardcode `localhost:8010`
- Data fetching: `useSWR` for polling, `useState`+`useEffect` for one-off
- Styling: Tailwind only — no inline styles, no CSS modules
- No `any` types; define interfaces in `lib/api.ts`

---

## 8. Environment and Commands

```bash
# Engine (Python venv)
cd engine && .venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Dashboard
cd dashboard && pnpm dev

# Both (Windows)
start_jarvis.bat

# Engine tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Dashboard build check (type checking)
cd dashboard && pnpm run build

# Secrets check (run before every push)
bash scripts/hooks/check-secrets.sh
```

Python venv: always use `engine/.venv/Scripts/python`, never system Python.
Node: always use `pnpm` — system `npm` is broken.

---

## 9. Playbook Routing

```
bugfix / investigation  →  playbooks/debug.md
new feature             →  playbooks/add-feature.md
refactor / cleanup      →  playbooks/refactor.md
test coverage / CI      →  playbooks/test.md
release / deploy        →  playbooks/release.md
```

---

## 10. External Tool Routing (JARVIS as Orchestrator)

**Read `TOOLS.md` for the complete routing map.** JARVIS TRADER is the central
intelligence — every task type has a designated external tool or Cowork skill.

Quick reference:

| Need | Go To |
|---|---|
| Live web research (news, macro, earnings, SEC filings) | Claude in Chrome / Kapture — see `TOOLS.md` Cat. 1 |
| Stored docs and strategy notes | Google Drive search — see `TOOLS.md` Cat. 1 |
| Trade data analysis, SQL, statistical work | `data:analyze`, `data:statistical-analysis` skills — see `TOOLS.md` Cat. 2 |
| Performance reports, P&L statements | `finance:financial-statements`, `data:interactive-dashboard-builder` — see `TOOLS.md` Cat. 2 |
| Debug a bug or pipeline failure | `engineering:debug` skill + `playbooks/debug.md` — see `TOOLS.md` Cat. 3 |
| Code review for safety-critical changes | `engineering:code-review` + gstack `/review` (both) — see `TOOLS.md` Cat. 3 |
| Start/stop engine, read logs | Desktop Commander — see `TOOLS.md` Cat. 4 |
| Store/retrieve reports and docs | Google Drive fetch/search — see `TOOLS.md` Cat. 4 |

**Safety rule applies to all tools:** No external tool can override `safety_layer.py`,
modify `INSTRUMENT_PARAMS`, or interact with IB Gateway without Tier 3 confirmation.

---

## 11. Completion Criteria

A task is complete ONLY when:

- [ ] Requested change is implemented or clearly scoped
- [ ] `cd engine && pytest tests/ -v` passes (0 failures)
- [ ] `cd dashboard && pnpm run build` produces 0 TypeScript errors
- [ ] `bash scripts/hooks/check-secrets.sh` shows no new secrets
- [ ] Safety layer tests pass: `pytest tests/test_safety_layer.py -v`
- [ ] All new safety-related code has a test
- [ ] Commit message follows conventional format: `feat:`, `fix:`, etc.
- [ ] No `.env`, credentials, or `client_secret*.json` staged
- [ ] Risks and follow-ups are documented

---

## 12. Supporting Files in This Skill Pack

| File | Contents |
|---|---|
| `SYSTEM_OVERVIEW.md` | What JARVIS TRADER is, who uses it, phase status |
| `ARCHITECTURE.md` | Modules, data flow, boundaries, risky surfaces |
| `COMMANDS.md` | All 80+ API endpoints with method, path, purpose |
| `TOOLS.md` | **Complete external tool routing map** — research, data, engineering, file/process |
| `playbooks/debug.md` | Reproduce → isolate → patch → verify |
| `playbooks/add-feature.md` | Spec → design → implement → test → ship |
| `playbooks/refactor.md` | Scope → extract → validate → review |
| `playbooks/test.md` | Locate gaps → write tests → validate coverage |
| `playbooks/release.md` | Pre-push checklist → commit → tag |
| `evals/acceptance-checklist.md` | Go/no-go gate for any change |
