---
repo: HKUSTDial/DeepFund
url: https://github.com/HKUSTDial/DeepFund
stars: 280
language: Python
license: MIT
archived: false
pushed_at: 2025-09 (active; NeurIPS 2025 accepted — exact ISO date unknown)
analyzed_at: 2026-06-18
recommendation: dedup
surfaces_with_value: [docs]
paper: arXiv:2505.11065
---

# HKUSTDial/DeepFund

## Core value proposition
DeepFund is an MIT-licensed Python research framework (NeurIPS 2025) that benchmarks
whether LLMs can make professional fund-investment decisions, with its headline
contribution being a *look-ahead-bias-free* "go-live" evaluation methodology: backtests
must be executed strictly chronologically via a `trading-date` parameter so no future
information can leak into a historical decision. It pairs a multi-agent stack (analysts →
optional planner → manager) with real-time persistence and a public arena leaderboard.
The transferable asset for jarvis-trader is the *discipline* (point-in-time evaluation),
not the code, which is research-grade and not built for live futures execution.

## How it maps onto jarvis-trader
**The primary value of this repo is already integrated.** `.claude/rules/testing.md:28`
contains a "No look-ahead bias (point-in-time discipline)" section that cites this exact
paper (`arXiv 2505.11065`, line 48), shipped via PR #107. So the rules surface is a
confirmed **dedup**, not a new integration.

(Process note for future analyses: an earlier draft of this evaluation, run against a
stale local checkout 35 commits behind `origin/master`, concluded the rule was *absent*
and flagged rules as integrate-now. Re-running against `origin/master` showed the section
present. Always analyze against fetched `origin/master`, not a stale local tree.)

The *plumbing* the rule references is real and richer than DeepFund's: `engine/backtest/
news_blackout.py`, `engine/backtest/regime.py`, and `engine/analytics/outcome_hygiene.py`
all exist, as do `engine/backtest/forward_test.py` (independent paper-OOS graduation with
BH-FDR) and `engine/backtest/paper_tracker.py` (live trade ledger). DeepFund's
`trading-date`-driven chronological replay is conceptually the same temporal contract
jarvis-trader already enforces via walk-forward + forward-test. On the agent side,
DeepFund's analyst/planner/manager workflow is a strict subset of jarvis-trader's richer
5-stage pipeline (`engine/agents/pipeline.py`: analysts → debate → trader → risk manager →
fund manager) — no porting value.

## Surface analysis

### 1. Engine code
defer (lean no-fit) — DeepFund is LangGraph + Supabase/SQLite research scaffolding for
equities arena benchmarking; `engine/backtest/` already has a deeper point-in-time
apparatus (`forward_test.py`, `paper_tracker.py`, `rolling_wfe_scheduler.py`,
`evaluation_harness.py`, family BH-FDR). The one idea worth borrowing is making the
simulated decision timestamp an *explicit required parameter* on the backtest entry point
(DeepFund's `trading-date`) so leakage is structurally impossible rather than
convention-enforced. Treat as a small hardening note, not a port.

### 2. Project rules
dedup — Already shipped. `.claude/rules/testing.md:28` "No look-ahead bias (point-in-time
discipline)" cites arXiv:2505.11065 (line 48). It complements `ml-pitfalls-defense.md`
(train-test leakage / purge / embargo from López de Prado) as the *temporal-contract*
companion. Do not re-add — note that a duplicate of this section was already consolidated
once (commit `7f5f88e`).

### 3. Project skills
no-fit — `backtest-runner`, `jarvis-wfe-check`, and `jarvis-search-discipline` already
cover the validation workflow.

### 4. Slash commands
no-fit — Nothing command-shaped to lift.

### 5. Subagents
no-fit — DeepFund's agents are a subset of the existing pipeline; `pipeline-debugger` and
`backtest-runner` cover this ground.

### 6. Docs
integrate-now (light) — This analysis stub, consistent with the existing files in
`docs/repo-integrations/`, so the repo is marked analyzed and not re-triaged.

### 7. Dev tooling
no-fit — No linters/CI/harness improvements applicable.

### 8. Dashboard
no-fit — DeepFund's arena leaderboard is a public-benchmark concept, irrelevant to a
single-operator paper dashboard.

### 9. Ops / messaging
no-fit — Nothing for IB Gateway / WhatsApp / Discord ops.

## Integration plan
1. **Rules — already done (dedup).** No action; value captured in `testing.md:28`.
2. **Docs.** This file marks the repo analyzed.
3. **Engine (optional, defer).** Backlog note: make the decision timestamp a required
   argument on the canonical backtest entry point so leakage is impossible by
   construction. Small hardening, not urgent.

## License & attribution
MIT — reuse permitted with attribution. The integration is methodological (a rule already
present + this doc, no copied code), so attribution is the existing citation line in
`testing.md` and this stub: paper "Time Travel is Cheating: Going Live with DeepFund for
Real-Time Fund Investment Benchmarking" (arXiv:2505.11065, HKUSTDial, 2025), repo
HKUSTDial/DeepFund (MIT). If DeepFund source is ever copied verbatim later, retain the MIT
LICENSE header — the current plan copies none.

## Effort estimate
S — one docs stub. The rules value is already shipped; no code, no tests, no safety
changes.

## Red flags
- **Stale-checkout trap (resolved).** Analyze against fetched `origin/master`; a local
  tree 35 commits behind reported the look-ahead rule as missing and nearly produced a
  duplicate of an already-shipped rule. The classification is dedup, not integrate-now.
- **Conceptual overlap, not duplication, with `ml-pitfalls-defense.md`.** That rule covers
  leakage/purge/embargo; the shipped testing.md section covers the temporal contract (news
  publish-time gating, label hygiene, live-vs-backtest parity). They are complementary.
- **No engine port warranted.** Pulling DeepFund code would add a LangGraph/Supabase
  dependency surface for capability jarvis-trader already exceeds. Ideas only, despite the
  permissive MIT license.
