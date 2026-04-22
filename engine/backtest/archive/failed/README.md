# Failed-gate-v2 strategies — archive index

Signal modules in `engine/backtest/` that were validated, failed gate v2, and are retained for reference only. **Do not wire these into live routing.** Re-investigating an archived strategy requires fresh gate v2 evidence.

| Module | Family | Gate v2 verdict | Date | Notes |
|--------|--------|-----------------|------|-------|
| `backtest/adx_ema_signals.py` | Trend-strength | FAIL | 2026-04-22 | Test PF 0.648 on MES 1h (n=90). No edge after ADX strength gate. |
| `backtest/atr_channel_signals.py` | Volatility breakout | FAIL | 2026-04-22 | Test PF 0.433 on MES 1h. Keltner-style breakout gave up the edge under ATR-regime filter. |
| `backtest/rsi_breakout_signals.py` | Mean-revert confirm | FAIL | 2026-04-22 | Test PF 3.66 but only n=3 — insufficient evidence floor for gate v2 per `gate_v2_policy.py`. |

The source modules remain in place (not moved) because `scripts/strategy_comparison.py` and their respective test files (`tests/test_*_signals.py`) still import them. Moving would break those imports. The in-file `STATUS:` header and this README are the durable "don't resurrect" markers.

See each module's docstring for the `STATUS: ARCHIVED — FAILED gate v2` line and reason.
