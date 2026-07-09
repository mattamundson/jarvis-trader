# MNQ Re-validation — Workstream Scope

> **Status: SCOPING ONLY. Not started, not executed.** This document defines what
> "re-validate MNQ" would concretely require, so a future session (on the trading
> box, with a real backtest engine and market data) can execute it deliberately
> instead of re-litigating the same failed result.
>
> Split out of `AUTONOMOUS_ACTIVATION_MES_MGC_PROPOSAL.md` §3a, decision (c),
> 2026-07-08.

---

## 1. Why MNQ is halted (the current record)

Per `engine/CLAUDE.md` and the archived gate-v2 verdicts in
`engine/data/gate_v2_verdicts/archive/MNQ_*.json`:

> MNQ | 1h | 0.57 | HALTED — trend/breakout/ORB all fail gate v2 (55 trades, 0 wins
> 2026-05-06/07); `DO_NOT_TRADE_SYMBOLS`

All **three** strategy families were tried, at multiple parameter ranks each
(`trend_rank1/2`, `breakout_rank1` through `rank7`, `orb_rank1` — 10+ archived
verdicts), all `FAIL`. Sample core-gate failure reasons from `MNQ_trend_rank1.json`
(created 2026-04-25, `rolling_wfo` refreshed 2026-04-21):

```
FAIL mbb_pf_ci_lower=0.6752 < 1.1        (bootstrap PF confidence interval too low)
FAIL p_positive_edge=0.7958 < 0.95       (edge probability below threshold)
FAIL mc_95th_dd_pct=13.4587 > 6.0        (Monte Carlo 95th-pct drawdown too deep)
dsr=0.159496 >= 0.1                       (not flagged as pure selection bias)
```

This is not a marginal miss — PF confidence interval, edge probability, and
drawdown all failed simultaneously. `DO_NOT_TRADE_SYMBOLS` in
`engine/backtest/signals.py:113` encodes this as a hard block, independent of any
runtime config (`AUTONOMOUS_ACTIVE_SYMBOLS` cannot override it).

---

## 2. What would actually constitute new evidence (not re-litigation)

Re-running the exact same backtest window/params and getting the same FAIL doesn't
move anything — that's already been done exhaustively. A re-validation only means
something if at least one of these is true:

1. **Meaningfully more/newer data.** The last verdict's `rolling_wfo` freshness is
   2026-04-21. A re-run against data through today adds a real out-of-sample window
   the original verdict never saw — this is the strongest legitimate case.
2. **A strategy family or parameter regime not yet tried.** All ranks tried so far
   are `trend`, `breakout`, `orb`. If a materially different approach (e.g. a
   mean-reversion or volatility-regime-gated variant, matching what unblocked
   MES/MGC) hasn't been tested on MNQ, that's new information, not a repeat.
3. **A regime-change argument with evidence**, not a hunch — e.g. documented
   structural change in MNQ's volatility/liquidity profile since April 2026 that
   would plausibly invalidate the prior failure mode (esp. the MC drawdown blowout).

Absent one of these, re-running is expected to reproduce `FAIL` and isn't worth the
compute or the review cycle.

---

## 3. Why this can't be executed from a cloud session

Confirmed in this session: `backtest-runner`'s two paths (per
`.claude/agents/backtest-runner.md`) both require infrastructure only available on
the trading box:

- **CLI:** `cd engine && .venv/Scripts/python -m backtest.run_backtest --symbol MNQ
  ...` — needs the engine's Python venv with market-data provider access
  (IB Gateway / Polygon), not present in this sandbox.
- **API:** `POST http://localhost:8010/backtest/run` — needs the live engine
  process running on the box.

This sandbox has no venv, no live engine, and no market-data connection. Anything
claiming to be a "fresh MNQ backtest" run from here would not be real — per this
repo's verification discipline, that's not something to fake.

---

## 4. Concrete next step (for a session on the box)

1. Confirm which of §2's three conditions actually applies before spending a
   backtest run — if none apply, don't run it; the halt stands.
2. If (1) applies: re-run the existing `trend`/`breakout`/`orb` families with the
   date range extended to present-day, using the same gate-v2 CLI/API path
   `backtest-runner` already documents.
3. If (2) applies: scope the new strategy family/parameters first (its own design
   decision — what edge hypothesis, matching the discipline used for MES/MGC's
   approval), then backtest it.
4. Any `PASS` verdict does **not** auto-unhalt MNQ. Per `engine/CLAUDE.md`'s
   flip-to-active criteria pattern (used for MES/MGC): needs `p_positive_edge >=
   0.6` fresh, gate-v2 `PASS`, **and explicit Tier-3 authorization from Amo** before
   `DO_NOT_TRADE_SYMBOLS` in `signals.py` is edited. That edit is itself a
   `[safety-review]` commit.
5. Only after that approval does MNQ get added to
   `AUTONOMOUS_ACTIVATION_MES_MGC_PROPOSAL.md`'s symbol list for real (not as a
   no-op).

---

## 5. Sign-off

- [ ] Amo: confirm which §2 condition justifies spending a re-validation run (or
      decline — halt stands)
- [ ] Backtest executed on the box (not from a cloud session)
- [ ] If `PASS`: separate Tier-3 approval + `[safety-review]` commit to edit
      `DO_NOT_TRADE_SYMBOLS`
- [ ] Only then: MNQ added to the autonomous-loop symbol list

_Scoping only. No backtest run, no code change, no config change by this document._
