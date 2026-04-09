# Validated Instruments

## Walk-Forward Efficiency (WFE) — Current Status

| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | **APPROVED** — paper trading active |
| MNQ | 1h | 0.57 | **APPROVED** — paper trading active |
| MGC | 1d | 0.14 | **HALTED** — overfit/small-sample |
| MES | 1h | 0.09 | **PAPER** — authorized 2026-04-09, WFE improvement pending |

## Capital & Validation Gates

- **Paper capital**: $10,000 total
- **Validation gate**: PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%, Trades ≥ 60, Days ≥ 30, DD ≤ 15%
- **Reference backtest** (in-sample only, not a live gate): MES 1h ~PF 5.3 / Sharpe 4.2 historically. WFE=0.09 means overfit — do not use for live decisions.

## Instrument Specs

| Instrument | Point Value | Tick Size | Typical ATR (1h) | Margin (paper) |
|------------|-------------|-----------|-------------------|----------------|
| MES | $5/pt | 0.25 pts = $1.25 | 15–25 pts ($75–$125) | ~$1,500 |
| MNQ | $2/pt | 0.25 pts = $0.50 | 40–80 pts ($80–$160) | ~$1,700 |
| MCL | $100/pt | 0.01 = $10 | per barrel | ~$500 |
