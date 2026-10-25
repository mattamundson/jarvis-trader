# Backtest critique checklist

**Purpose:** standard critique pass for any JARVIS strategy backtest before the verdict is recorded in the strategy registry. Derived from `claude-trading-skills`/`backtest-expert`, `tradingview-mcp`/`strategy-report`, and the audit's tooling-stack backtest-gate entry.

**Scope:** applies to engine backtests (`engine/backtest/`) and any Pine-script backtest captured via TradingView MCP. Not a substitute for walk-forward or paper-shadow validation — those are separate promotion gates.

---

## 1. Trade identity and data hygiene

- [ ] Bar-aligned: signals evaluated on bar `t` use only data from `<= t` (no `t+1` close in an entry decision). Confirm no `shift(-1)` / `illy` patterns in the entry logic.
- [ ] Corporate-action / continuous-contract handling documented: allocation/roll convention stated (e.g. MES continuous roll at first notice / expiry), and backtest bars match the live data source shape.
- [ ] Slippage/fee model stated explicitly: commission per contract, slippage in ticks, any spread assumption. If the backtest used a different model than the runtime config, that divergence is recorded (see `mes_sma_trend_vix_pctile` cost-tier divergence note).
- [ ] Look-ahead guard: no use of `high`/`low`/`close` of the same bar for an intraday-entry signal that would have been unavailable at decision time.
- [ ] Survivorship-free instrument set: if the universe is more than one contract, confirm no instrument was removed from the test after the fact.

## 2. Return and risk metrics

- [ ] Net PnL and CAGR (or annualized return) reported for the full test window.
- [ ] Max drawdown ($ and % of notional) reported.
- [ ] Sharpe and/or Sortino reported; if only one, say why.
- [ ] Profit factor reported (gross profit / gross loss). The strategy-report skill treats >1.5 as a soft target — flag anything below it.
- [ ] Trade count reported; if low, flag that metric stability is weak.
- [ ] Average trade ($ and % of risk) reported; win rate reported alongside.
- [ ] Max consecutive losses reported.
- [ ] Long vs short breakdown reported if the strategy trades both sides.

## 3. Parameter stability and overfitting guard

- [ ] Parameter sensitivity stated: what happens to the headline metrics if the key lookback/threshold is moved ±10–20%?
- [ ] If a parameter sweep was run, the chosen parameter set is not the single best point in-sample unless there's an out-of-sample or walk-forward justification.
- [ ] Walk-forward or out-of-sample window stated if claimed; the split point is before the review date.

## 4. Regime split

- [ ] Results split by at least one regime dimension (e.g. trending vs range-bound, high vs low VIX, bull vs bear SPX) if the strategy is regime-sensitive.
- [ ] If the strategy collapses in one regime, that's documented as a known failure mode, not hidden.

## 5. Monte Carlo / ruin risk

- [ ] If the strategy is live or near-live, a simple Monte Carlo of trade-order reshuffles or equity-curve bootstrap is run and the ruin/deep-drawdown probability is recorded.
- [ ] If not run, say why (e.g. insufficient trade count).

## 6. Execution realism (separate leg — not satisfied by backtest alone)

- [ ] Paper/live fill comparison planned or completed; the backtest cost model is not assumed to match live fills.
- [ ] For `mes_sma_trend_vix_pctile`, this leg is explicitly NOT closed: the backtest used `COST_SWEEP_TIERS` (commission 0.62, slippage 2.0 ticks) which diverges from `engine/config.py` defaults (commission 1.42, slippage 1.0 tick). The execution-realism leg remains open pending a fill-comparison study.

## 7. Verdict recording

- [ ] Verdict recorded in the strategy registry entry with: hypothesis, instruments, data source, features, parameters, train/test windows, WFO verdict, paper verdict, owner, promotion state.
- [ ] Evidence path(s) pointing to the backtest report and any critique artifacts.
- [ ] If the verdict is `robustness`, the open legs are enumerated (e.g. "execution-realism leg not closed").

---

## Quick severity guide

- **Blocker:** data-leakage / look-ahead confirmed and not fixed → do not promote.
- **P1:** cost model divergence from runtime not recorded → record before verdict.
- **P2:** regime split missing on a regime-sensitive strategy → add before paper.
- **P3:** Monte Carlo not run on a low-trade-count strategy → note as caveat.
