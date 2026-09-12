# Plan — Options Decision Board / Volatility Regime Phase 1

## Finish line

Create a read-only, analysis-only options decision-board backend tranche that improves JARVIS market-analysis quality without touching live trading, risk config, kill-switches, `.env`, order routing, or DO_NOT_TRADE policy.

## Scope constraints

- No live trading/risk/kill-switch/config changes.
- No operational commands for MCL or MNQ.
- Analysis-only outputs must label source quality and reject reasons.
- Tests must verify numeric probability and payoff math.

## Tranche 1 deliverables

1. Repair/confirm the existing SPY/QQQ implied options snapshot probability ladder:
   - include `p_touch` and `p_fail` per ladder row;
   - enforce `p_touch >= p_close` where applicable;
   - keep no-extrapolation behavior.
2. Add a pure `analysis/options_opportunity_board.py` module that consumes the existing delayed CBOE snapshot shape and produces ranked, defined-risk candidates:
   - bull call debit spread;
   - bear put debit spread;
   - put credit spread;
   - call credit spread;
   - no naked/unlimited-risk structures;
   - max loss, max gain/credit, breakeven, POP proxy, EV proxy, EV/max_loss, liquidity score, reject reasons.
3. Add `GET /options-signals/opportunity-board` as a read-only endpoint built from `latest.json`.
4. Add unit/router tests covering payoff math, liquidity filters, reject reasons, and endpoint behavior.
5. Verify with targeted pytest. If dashboard files are touched in a later tranche, verify with `tsc`, build, and Playwright.

## Follow-on tranches

- Tranche 2: dashboard opportunity-board card near Mission Control / signals, using `fetchEngine` only.
- Tranche 3: battle-card report generator combining SPY/QQQ/VIX regime + touch/close/fail probabilities + candidate structures.
- Tranche 4: chain snapshot ledger for calibration of implied move vs realized move and structure outcomes.
- Tranche 5: journal/error taxonomy integration.
