# Instrument onboarding (futures)

## Steps

1. **Watchlist** — Add symbol to `FUTURES_WATCHLIST` in `engine/config.py` (or env), aligned with capital and risk limits.
2. **Signals** — If bar interval or regime logic differs, update canonical parameters in `engine/backtest/signals.py` (Tier 3 change — review required).
3. **Walk-forward / WFE** — Run rolling WFE and backtest scripts; record WFE and verdict in `engine/backtest/paper_config.py` (or equivalent status source) and dashboard paper-status endpoint.
4. **Paper config** — Ensure `paper_config` / validation tracker entries match approved TF and status (`ACTIVE` vs halted).
5. **Dashboard** — Confirm command center and validation pages show the new row; no auto-live until status APPROVED.
6. **Pipeline** — Run `POST /pipeline/run` in paper; if `requires_human` is true, use **Pending approvals** page before ledger entries.

## Do not skip

- MES-class WFE failures (below gate) must remain **DO NOT TRADE** until re-validated.
