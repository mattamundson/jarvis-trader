---
repo: FinStep-AI/ContestTrade
url: https://github.com/FinStep-AI/ContestTrade
stars: (mid-hundreds; from awesome-trading-agents)
language: Python 3.10+
license: Apache-2.0
archived: false
pushed_at: 2026 (actively maintained)
analyzed_at: 2026-06-17
recommendation: partial-integrate
surfaces_with_value: [engine]
paper: arXiv:2508.00554
---

# FinStep-AI/ContestTrade

## Core value proposition
An event-driven multi-agent stock-selection framework whose distinguishing feature is a
**two-stage internal contest**: parallel agents each produce a candidate output, then a
competition mechanism scores those candidates and keeps only the winners to synthesize a
final decision. This is the one mechanism in `LLMQuant/awesome-trading-agents` that
jarvis-trader does **not** already have — our debate is adversarial (one bull vs. one
bear), not a tournament across *many* competing candidates. Apache-2.0, so code reuse is
permitted with attribution.

## How the contest works (the part worth stealing)
Two competition layers, both "select-best-from-many":

1. **Data / factor contest (Stage 1)** — multiple data-analysis agents each distill raw
   market data into a structured "text factor." An internal evaluation scores each
   factor's value and assembles an optimal *factor portfolio* (the winners), discarding
   low-value factors before they can pollute downstream reasoning.
2. **Research / proposal contest (Stage 2)** — multiple research agents, each operating
   under a distinct configurable "trading belief" (e.g. aggressive event-driven vs.
   conservative dividend/buyback), submit trade proposals. A second evaluation scores
   proposals on "robustness and effectiveness" and synthesizes the survivors into one
   asset-allocation decision.

Beliefs are user-configurable via `belief_list.json`; results are written as Markdown
reports to `agents_workspace/results/`. No backtesting module ships with it — it is a
real-time signal generator, which is the main gap for our purposes.

## How this maps onto jarvis-trader
| ContestTrade concept | jarvis-trader home | Relationship |
|---|---|---|
| Stage-1 factor contest | `engine/analytics/ic_ensemble.py` | **Strong dedup.** We already select/weight analyst signals by rolling Information Coefficient — a quantitative, outcome-grounded contest. ContestTrade's LLM-judged factor scoring is *weaker* than our IC weighting (no realized-P&L grounding). Do not replace IC. |
| Stage-2 proposal contest | `engine/agents/debate.py`, `backtest/consensus.py`, `candidate_registry.py` | **Partial fit.** Our debate is 1-bull-vs-1-bear; the novel idea is running *N* trader proposals under different "beliefs" and selecting the best, rather than synthesizing a single trader verdict. |
| "Trading beliefs" config | `engine/strategies/registry.py`, `belief_list.json` analog | New: parameterized agent personas as a config file is a clean pattern we lack. |
| Markdown report output | `engine/data/morning_briefs/`, post-trade reports | dedup. |

## Surface analysis

### 1. Engine code
**partial-integrate** — One concrete, bounded experiment worth a spike: a **belief-diverse
trader ensemble**. Run the existing `TraderAgent` N times under distinct persona/belief
prompts, then select the winning proposal via a *quantitative* judge (reuse IC / expected
edge from `ic_ensemble.py` and `analytics/signal_quality.py`), not an LLM judge. This
keeps the safety-critical selection deterministic while borrowing ContestTrade's
many-candidates-then-select structure. Gate behind the existing debate stage; never let
the LLM judge override risk/fund-manager checks.

### 2. Project rules
**no-fit** — Nothing rule-shaped beyond what we already capture.

### 3. Project skills
**no-fit** — No reusable skill content.

### 4. Slash commands
**no-fit.**

### 5. Subagents
**dedup** — Persona agents overlap conceptually with our `.claude/agents/` roster; no new
subagent warranted.

### 6. Docs
**partial-integrate** — Worth a short note in `docs/` contrasting adversarial debate vs.
tournament selection, so the architectural choice is recorded.

### 7. Dev tooling
**no-fit** — Docker/uv setup is theirs; we use venv + PM2.

### 8. Dashboard
**no-fit.**

### 9. Ops / messaging
**no-fit** — A-share data plumbing (AKShare/Tushare) is irrelevant to MCL/MNQ futures.

## Integration plan
Single spike, its own branch, no safety files touched:
1. Add a `belief_list`-style config of 3-4 trader personas (aggressive momentum,
   conservative mean-reversion, etc.) under `engine/strategies/`.
2. In the pipeline's trader stage, run the `TraderAgent` once per belief in parallel
   (reuse existing async fan-out from Stage 1 analysts).
3. Score proposals with a **deterministic** judge built from `ic_ensemble.py` +
   `signal_quality.py` (expected edge / historical IC), not an LLM. Select the winner.
4. Write a failing unit test fixing known belief inputs → expected winner, implement to
   pass. Verify a backtest does not regress vs. the single-trader baseline (revert if
   it does — per `meta-discipline.md`, <10% gain on a refactor is a revert).
5. The risk-manager and fund-manager stages remain untouched and still gate the winner.

## License & attribution
**Apache-2.0** — code may be reused with attribution. If any ContestTrade code is copied,
add an attribution header and note it in the commit body. Most likely we reimplement the
*pattern* in our own style rather than copy code, given the A-share-specific plumbing.

## Effort estimate
**M** (2-8hr) for the belief-ensemble spike including test + backtest comparison.

## Red flags
- **Do not let an LLM judge make the selection** — that would violate
  `.claude/rules/safety.md` (no LLM-driven decisions in the safety path). The contest
  selector must be deterministic and sit *before* the risk/fund-manager gates, never
  replace them.
- ContestTrade ships **no backtest harness** — we must validate any borrowed pattern in
  our own `engine/backtest/` before trusting it.
- A-share / news-event orientation; the data side is irrelevant to our futures focus.
  Value is purely the tournament-selection structure, not the data agents.
- Our `ic_ensemble.py` is a *stronger* (outcome-grounded) contest than theirs for
  signal weighting — resist replacing it with LLM-judged factor scoring.
