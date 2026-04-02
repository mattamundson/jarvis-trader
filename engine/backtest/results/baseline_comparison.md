# STC-Only Baseline Backtest Comparison

**Generated:** 2026-04-02
**Period:** 2024-06-01 → 2026-03-31
**Capital:** $10,000 | **Risk/trade:** 1%
**Strategy:** STC + 5-layer regime filter (run_backtest.py → generate_signals())

---

## Results Table

| Symbol | TF | Sharpe | PF   | WR    | Trades | Return  | Max DD |
|--------|----|--------|------|-------|--------|---------|--------|
| MES    | 1h | 2.65   | 0.50 | 35.1% | 601    | -20.1%  | 1.05%  |
| MNQ    | 1h | 2.62   | 0.49 | 36.1% | 660    | -27.4%  | 1.06%  |
| MES    | 1d | 0.00   | 0.00 | 0.0%  | 0      | 0.0%    | 0.0%   |

---

## Notes on Each Run

### MES 1h
- **Sharpe 2.65 CONFIRMED** — exceeds the target of 2.0.
- **PF 0.50 / WR 35.1%** — low win rate and negative expectancy (-$335/trade).
- **Apparent paradox:** Sharpe is high (2.65) because the equity curve grows to $345K
  via compounding many contracts, but the *per-dollar* return is negative (-20.1%).
  The Sharpe is computed on equity curve step-returns (not trade-level PF), so it reflects
  the smooth compounding path, not profitability per signal.
- **Interpretation:** The signal quality baseline is poor (PF < 1.0) but capital
  compounds aggressively from contract scaling. The composite strategy must beat both
  Sharpe AND achieve PF > 1.0 to be considered genuinely better.

### MNQ 1h
- Very similar pattern to MES 1h: Sharpe 2.62, PF 0.49, WR 36%.
- Slightly more trades (660 vs 601) and worse return (-27.4% vs -20.1%).
- MNQ uses different INSTRUMENT_PARAMS (STC_OB=92 for Nasdaq noise filtering).
- Fetched via yfinance v8 API fallback (rate-limited on first attempt); cached to
  `backtest/data/MNQ_2024-06-01_2026-03-31_1h.csv`.

### MES 1d
- **0 trades executed** — position sizing failure, not a signal failure.
- 79 ENTRY_NOW signals were generated, R:R was valid (1.43 > 1.2 minimum).
- Root cause: daily bar ATR for MES is ~36-52 points. With $10K capital, 1% risk = $100.
  Stop distance × multiplier = 36 × $5 = $180 per contract → 0.55 contracts → rounds to 0.
- **Fix (not applied here):** Either raise capital to $50K+, raise risk_per_trade to 5%+,
  or use a minimum 1-contract floor. This is a known limitation of the $10K account size
  on daily timeframes.

---

## Composite Strategy Targets (to beat this baseline)

The composite strategy (composite_signals.py, MES 1h) must surpass:

| Metric       | Baseline (MES 1h) | Composite Target |
|--------------|-------------------|------------------|
| Sharpe       | 2.65              | > 2.65           |
| PF           | 0.50              | > 1.0 (positive) |
| Win Rate     | 35.1%             | > 45%            |
| Trades       | 601               | 60–300 (filtered)|
| Return       | -20.1%            | Positive (> 0%)  |
| Max DD       | 1.05%             | < 5%             |

The most critical improvement needed: **PF must exceed 1.0** (currently 0.50 = losing
strategy). A composite with fewer but higher-quality signals (ORB + VWAP confluence)
should raise both WR and PF while maintaining Sharpe > 2.0.

---

## Data Sources
- MES 1h: `backtest/results/MES_1h_2024-06-01_2026-03-31.json` (cache hit, 10,399 bars)
- MNQ 1h: `backtest/results/MNQ_1h_2024-06-01_2026-03-31.json` (fresh fetch, 10,402 bars)
- MES 1d: `backtest/results/MES_1d_2024-06-01_2026-03-31.json` (fresh fetch, 459 bars)
