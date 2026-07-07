---
repo: ulab-uiuc/live-trade-bench
url: https://github.com/ulab-uiuc/live-trade-bench
stars: 159
language: Python
license: PolyForm Noncommercial License 1.0.0 (treat as proprietary for our purposes — no commercial reuse)
archived: false
pushed_at: 2025-10-28
analyzed_at: 2026-06-18
recommendation: defer
surfaces_with_value: [rules, docs]
---

# ulab-uiuc/live-trade-bench

## Core value proposition
A FastAPI platform from UIUC's uLab that runs multiple LLM trading agents (GPT, Claude,
Gemini) live and in parallel against real markets — US equities (Yahoo Finance) and
Polymarket prediction markets (CLOB API) — scoring them on realized portfolio returns
rather than backtests, explicitly to dodge backtest overfitting. It is a
*benchmark/leaderboard* for comparing models-as-traders, not a single-operator trading
engine.

## How it maps onto jarvis-trader
The thesis — "live forward evaluation is the honest scoreboard; backtests overfit" — is
already an enshrined jarvis-trader invariant. `.claude/rules/testing.md:28` ("No
look-ahead bias / point-in-time discipline") cites DeepFund (arXiv 2505.11065) for exactly
this, and `engine/backtest/forward_test.py` operationalizes it: it forward-tests frozen
candidates and LLM "decision lineages" on independent paper OOS windows with family-wide
BH-FDR correction and a fail-closed graduation rule. `engine/backtest/paper_tracker.py` is
the live-trade ledger with kill thresholds, and `engine/backtest/evaluation_harness.py` is
the fixed two-layer (statistical validity → risk-adjusted return) screening gate.
live-trade-bench's evaluation is *shallower* than ours — it ranks agents on raw realized
return with no multiple-testing correction, no DSR, no permutation null (the gaps
catalogued in `.claude/rules/ml-pitfalls-defense.md`). Where the repos overlap is
multi-LLM-agent comparison and Polymarket — and jarvis-trader already has Polymarket
coverage (`engine/markets/polymarket/`, `engine/execution/polymarket_connector.py`,
`dashboard/app/polymarket/`, all verified present). The one structurally novel idea is
running *the same decision across multiple model providers simultaneously and ranking
them* as a standing benchmark; jarvis-trader runs a fixed cost-tiered model stack
(`jarvis-cost-routing`), not a head-to-head model bake-off.

## Surface analysis

### 1. Engine code
no-fit — License is PolyForm Noncommercial; jarvis-trader deploys real capital
(commercial purpose the license forbids), so **no code may be copied**. License aside, the
live-eval machinery already exists and is more rigorous: `engine/backtest/forward_test.py`,
`paper_tracker.py`, `evaluation_harness.py`. Their fetcher layer duplicates capabilities
we already have.

### 2. Project rules
partial-integrate — One citable idea: our look-ahead rule already cites DeepFund;
live-trade-bench is an independent, same-thesis project worth adding as a *one-line
corroborating reference* in `.claude/rules/testing.md`. No code, no license entanglement —
citing a project name + URL is fine. Low value, additive only, and only on explicit
request (rules edits are not implicit outputs per `meta-discipline.md` rule 3).

### 3. Project skills
no-fit — Nothing maps to a reusable skill beyond `repo-integrator`/`backtest-report`.

### 4. Slash commands
no-fit — No command pattern to extract.

### 5. Subagents
no-fit — jarvis-trader's `pipeline-debugger`/`backtest-runner`/`safety-reviewer` already
exceed this repo's single base-agent abstraction.

### 6. Docs
integrate-now (light) — This analysis doc, so the repo isn't re-triaged. The durable
takeaway is the "multi-provider head-to-head model leaderboard" concept as a *future
feature candidate*, flagged like meta-labeling is parked in `ml-pitfalls-defense.md` —
tracked, not built.

### 7. Dev tooling
no-fit — Poetry + FastAPI + a JS frontend; jarvis-trader standardizes on pnpm + its own
venv. Nothing to adopt.

### 8. Dashboard
dedup — A public agent-leaderboard UI is the repo's strongest UI idea, but jarvis-trader
already has `dashboard/app/scorecard/` and `dashboard/app/polymarket/`. A model-vs-model
leaderboard is net-new only if jarvis-trader adopts multi-provider head-to-head trading,
which it does not today. No code reuse permitted regardless (license + dashboard rules).

### 9. Ops / messaging
no-fit — No alerting/messaging layer to mine.

## Integration plan
Minimal, additive and license-safe (reference only, zero code copied):
1. (optional, on request) Add one corroborating citation to `.claude/rules/testing.md`
   next to the existing DeepFund reference.
2. This `docs/repo-integrations/ulab-uiuc__live-trade-bench.md`, capturing the one
   future-feature candidate (multi-provider head-to-head model leaderboard).
No engine, skill, command, subagent, dashboard, tooling, or ops integration.

## License & attribution
PolyForm Noncommercial License 1.0.0 — **not** in the permissive set. It permits use only
for noncommercial purposes; a private capital-deploying trading engine is commercial in
intent. Treat as **ideas-only: copy no source code, no config, no UI**. Attribution for the
permitted ideas-level borrowing goes in the two markdown files only (name + URL + license).

## Effort estimate
S — two optional markdown edits, no code.

## Red flags
- License is the hard blocker: PolyForm Noncommercial forbids the commercial use this
  codebase serves. Any copied snippet is a violation. Keep it strictly conceptual.
- Heavy duplication: live-eval and Polymarket coverage already exist and are more
  statistically rigorous (BH-FDR, fail-closed graduation) than this repo's raw-return
  ranking.
- Single v0.0.1 release (Oct 2025), 159 stars — early-stage academic benchmark, not a
  battle-tested production library.
- Its evaluation lacks the multiple-testing / DSR / permutation defenses jarvis-trader
  mandates (`ml-pitfalls-defense.md`) — do not regress toward "rank on realized return."
