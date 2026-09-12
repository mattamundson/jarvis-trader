# Backtest critique checklist

Use this checklist before treating any strategy result as useful evidence.

## Identity

- Strategy ID is stable and unique.
- Source is recorded: repo, note, notebook, prompt, paper, or human idea.
- Asset class, symbol(s), session, timeframe, and venue assumptions are explicit.
- Hypothesis is falsifiable.

## Data integrity

- Feed/source is recorded.
- Timestamp timezone and session calendar are explicit.
- Range, missing bars, duplicates, and corporate/contract adjustments are checked.
- Futures rolls, continuous-contract rules, and symbol mappings are documented.
- Feature calculation cannot use future bars or revised future information.

## Execution assumptions

- Order type and fill model are stated.
- Fees, commissions, exchange fees, spread, and slippage are included.
- Position sizing is explicit.
- Stop/target/trailing-stop direction invariants are tested.
- Leverage/margin constraints are realistic for the intended account.

## Statistical quality

- Net PnL/return, max drawdown, Sharpe/Sortino, profit factor, exposure, trade count, win rate, payoff ratio, and expectancy are reported.
- Confidence intervals or bootstrap estimates are included for fragile metrics.
- Multiple-testing / data-snooping risk is addressed.
- Parameter sensitivity is shown; the winner is not a single isolated spike.
- Regime split is evaluated.
- Walk-forward or out-of-sample period is separate from selection/tuning.
- Monte Carlo/path-risk estimate is included where applicable.

## Promotion gate

A strategy cannot move beyond research unless:

1. Data contract passes.
2. Backtest report passes checklist.
3. WFO/OOS evidence passes.
4. Paper shadow produces enough observations for drift review.
5. Promotion decision records evidence paths and known failure modes.
6. Safety review passes if execution/risk/broker/gate behavior changes.

## Red flags

- Annualized returns from short tests presented without caveat.
- Low trade count with high confidence claims.
- Missing slippage/fees.
- Unclear futures roll handling.
- Parameter set selected after looking at OOS.
- Chart-only strategy with no machine-readable rules.
- LLM-generated strategy accepted without deterministic replay.
