# Paper → Real-Money Promotion Runbook

**Owner:** Matt Morrison
**Last reviewed:** 2026-04-21
**Applies to:** Any JARVIS-TRADER strategy that is paper-approved and has live paper trades accumulating.

This runbook defines the objective criteria a strategy must satisfy before real capital is committed. It exists so that the promotion decision is not re-negotiated under P&L pressure. Write it now, follow it later.

---

## Philosophy

Real money deployment is **not** the reward for a good backtest — backtests are a necessary but insufficient filter. Promotion requires evidence that the *live* behavior matches the *modeled* behavior, with enough sample size to trust the comparison.

**Default stance: do not promote.** The burden of proof is on the strategy, not on the reviewer.

---

## Hard Gates (all must pass)

| # | Gate | Threshold | How to measure |
|---|---|---|---|
| 1 | Minimum live paper trades | **≥ 100** | `SELECT COUNT(*) FROM paper_trades WHERE strategy=? AND symbol=? AND realized=true` |
| 2 | Realized profit factor | **> 1.4** | Below backtest PF to account for live-execution degradation and small-sample uncertainty |
| 3 | Realized max drawdown | **< 6%** of starting equity | Peak-to-trough on the paper equity curve over the 100-trade window |
| 4 | Distribution match with backtest | KS-test **p > 0.10** | Live trade P&L distribution vs. bootstrapped backtest distribution — if live is meaningfully different, the backtest is not representative |
| 5 | Monte Carlo Tier A passes | 5th-percentile PF > 1.0 | Block bootstrap over live trades; 5th pct is worst reasonable case |
| 6 | Three consecutive quarterly re-validations | All pass | Quarter = 90 calendar days of operation; re-validation = full WFO + Tier A MC |
| 7 | Mean execution slippage | **≤ 1.5× backtest assumption** | From `fill_quality` table; if live slippage is 2× the assumption, either the assumption is wrong or the strategy's edge disappears under real fills |
| 8 | No kill-switch activations due to strategy performance | Zero | Kill-switches fired for external reasons (credit outage, data staleness) do not count; performance-driven kill events do |
| 9 | Documented operational continuity | Written runbook | If the owner is unavailable, a second human must be able to maintain, pause, and unwind without guidance |

---

## Soft Gates (weight against, can be overridden with written rationale)

| Soft gate | Concern | Override requires |
|---|---|---|
| Trade count in "stress regimes" (VIX > 25, trending bear, news shocks) | If all 100 trades are in one regime, the strategy is not tested | Explicit note of regime representation; may require more trades |
| Parameter sensitivity stability | Re-running WFO each quarter should keep same winner (or adjacent) | If winner shifted, document why and re-test |
| Correlation with other live strategies | Portfolio risk | If Rolling 30d corr with other live > 0.7, reduce combined sizing |
| Contract-roll experience | MES rolls quarterly; strategy must survive a roll cleanly in paper | At least 1 successful paper roll observed |

---

## Escalation — what "promoted" means in practice

Promotion does **not** mean "trade the same size live as in paper." It means "start trading live *at smaller size* and scale up on continued performance."

### Phase 1 — Seed (weeks 0–4 post-promotion)
- Size: **10%** of target live size
- Daily review of each trade
- Any underperformance ≥ 1σ from model → pause + human review
- Automatic pause after consecutive-loss circuit breaker trips

### Phase 2 — Ramp (weeks 4–12)
- Size: 25% → 50% → 75% in biweekly steps if each step passes a mini-review:
  - Realized PF in period ≥ 0.8 × target PF
  - No unexplained divergences from backtest
- Step held if either is violated; step-down if both violated

### Phase 3 — Full size (week 12+)
- Size: 100% of target
- Weekly review replaces daily
- Monthly Tier A Monte Carlo re-run
- Quarterly full re-validation

---

## Automatic De-promotion Triggers

The strategy returns to paper (or off) without human intervention when any of these fire:

1. Drawdown from peak equity ≥ **10%**
2. Rolling 30-day realized Sharpe < **0.5** for 5 consecutive days
3. Three consecutive losing trades (triggers 24h pause; second trip within 7 days = de-promote)
4. Monte Carlo 5th-percentile PF falls below **0.9** on any scheduled re-run
5. Correlation with another live strategy exceeds **0.8** (combined risk limit breach)
6. Any kill-switch event that appears strategy-driven (not infrastructure-driven)

De-promotion is *not* a strategy kill. It returns to paper and requires repeating Phase 1 before re-promoting.

---

## Strategy Retirement Criteria

Pre-commit to when a strategy should be abandoned, not just paused:

- Six consecutive months of realized PF below 1.0 in paper
- Two de-promotion events within 12 months
- Root-cause analysis concludes the modeled edge is no longer present in the market (structural change)

Retirement is a decision, not a drift. Write the retirement memo on the day of retirement; do not let a dead strategy quietly consume dashboard space.

---

## Reviewer Checklist (pre-promotion)

Run through this with outputs saved to `docs/promotion-reviews/<strategy>-<date>.md`:

- [ ] Gate 1 (≥100 trades) — actual count: ___
- [ ] Gate 2 (PF > 1.4) — realized PF: ___
- [ ] Gate 3 (maxDD < 6%) — observed: ___%
- [ ] Gate 4 (KS-test p > 0.10) — p-value: ___
- [ ] Gate 5 (MC 5pct PF > 1.0) — 5pct PF: ___
- [ ] Gate 6 (3 quarterly re-valid) — dates passed: ___
- [ ] Gate 7 (slippage ≤ 1.5× model) — ratio: ___
- [ ] Gate 8 (zero perf-driven kill events) — confirmed: ___
- [ ] Gate 9 (runbook exists) — link: ___
- [ ] All soft gates addressed or overridden with rationale
- [ ] Phase 1 start size calculated: ___ contracts
- [ ] De-promotion triggers wired to kill-switch
- [ ] WhatsApp alert path verified end-to-end (test ping delivered)

---

## Current Status by Strategy (2026-04-21)

| Strategy | Symbol | Paper trades | Status |
|---|---|---|---|
| SMA(50,200) + 2.0×ATR | MES | 0 live | Pre-promotion — awaiting first live paper trade |
| (none validated) | MCL | — | Gated HOLD (T5 Option B) until per-symbol edge re-derived |
| (none validated) | MNQ | — | Gated HOLD (T5 Option B) |
| (none) | MGC | — | Not in scope |

## Related documents

- `docs/session-logs/handoff-2026-04-20-mes-profitability.md` — why SMA(50,200) was chosen
- `docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md` — wiring detail
- `docs/monte-carlo-mes-sma-2026-04-21.md` — Tier A stress-test baseline (expected output of the 2026-04-21 MC run)
- `docs/ib-gateway-paper-e2e.md` — execution path validation
- Memory: `project_per_symbol_strategy_decision.md` — the Option B decision context
