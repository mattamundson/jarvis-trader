# avg_loss Investigation — 2026-06-01

## Root Cause

Three sources, in order of impact:

1. **Test fixture pollution**: `test-import-single-fixture-001` (symbol=TEST, pnl=+$50) was inserted into the live `paper_trades` DB by `test_integration.py::test_import_trades_single` hitting the running engine. Removed 2026-06-01. This inflated WR from 1/4 (25%) to 2/5 (40%) and depressed avg_loss from $120 to the same $120 but with a false +$50 win.

2. **IBKR paper stop slippage**: Both MGC losses (2026-05-08) exited at 4705.0 — 3-4 pts below their set stops (4708.78 and 4707.98). Both were real IBKR paper fills, not paper_runner simulation. The gap-through on a fast move caused the actual fill to land below the stop level.

3. **Correlated entries, same-day losses**: Both MGC long trades entered within 1 hour of each other on the same day during an adverse move. The ATR trailing stop (2.0x) was correctly set at ~14.6 pts but the market moved ~17-18 pts against both trades.

## Real Stats After Fixture Removal (4 trades)

| Metric | Value |
|---|---|
| Total trades | 4 |
| Wins | 1 (MCL, halted instrument) |
| Losses / breakeven | 3 |
| Win rate | 25% |
| Avg win | $100 |
| Avg loss | $120 (avg of $184, $176, $0) |
| EV/trade | 0.25 × $100 − 0.75 × $120 = −$65 |

## Decision: No Parameter Change

`atr_trail_mult=2.0` is the WFO champion for both MES and MGC — validated on 16 MES OOS trades and 12 MGC windows. Changing it on 4 real trades would overfit to noise. Fix: collect 60+ trades before reconsidering stop width.

## Action Items

- [x] Deleted test fixture from live DB
- [ ] Add DB cleanup to `test_import_trades_single` teardown so tests don't pollute live DB
- [ ] Investigate IBKR paper order type — use stop-limit instead of stop to bound slippage
