# Validated Instruments

## Walk-Forward Efficiency (WFE) — Current Status

> Reflects the 2026-05-24 Tier-3 instrument flip (Wave 3 expansion). Authoritative
> source: `engine/CLAUDE.md` Active Instruments + `engine/config.py`.

| Symbol | TF | Metric | Status |
|--------|----|--------|--------|
| MES | 1h | p_edge 0.75 | **APPROVED** — paper active (Tier-3 2026-05-24); SMA(60,200) trend, atr_trail_mult=2.0; ALT gate v2 PASS |
| MGC | 1h | p_edge 0.6842 | **APPROVED** — paper active (Tier-3 2026-05-24); SMA(50,120) trend, atr_trail_mult=2.0; ALT gate v2 PASS |
| MCL | 1h | WFE 0.82 | **HALTED** — `DO_NOT_TRADE`; hypotheses A–E exhausted 2026-05-07 |
| MNQ | 1h | WFE 0.57 | **HALTED** — `DO_NOT_TRADE`; trend/breakout/ORB all fail gate v2 |
| M2K | 1h | — | **REJECTED** — SMA/ORB/Donchian rank-1 all FAIL 2026-05-24 |

## Capital & Validation Gates

- **Paper capital**: $10,000 total
- **Validation gate (legacy generic)**: PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%, Trades ≥ 60, Days ≥ 30, DD ≤ 15%
- **Gate v2 (current)**: ALT path requires `mc_95th_dd ≤ 7%`, `dsr ≥ 0.30`, `rolling_wfo = MODERATE+`, `fixed_params_min_pf ≥ 1.2`, plus Tier-3 authorization. See `docs/strategic/06_VALIDATION_GATES.md`.
- **Reference backtest** (in-sample only, not a live gate): MES 1h ~PF 5.3 / Sharpe 4.2 historically (`ui_only` / superseded). The old 1h `WFE=0.09` headline is superseded — MES was promoted to active paper on 2026-05-24 via the gate-v2 ALT path (p_edge 0.75), not the old WFE metric.

## Instrument Specs

| Instrument | Point Value | Tick Size | Typical ATR (1h) | Margin (paper) |
|------------|-------------|-----------|-------------------|----------------|
| MES | $5/pt | 0.25 pts = $1.25 | 15–25 pts ($75–$125) | ~$1,500 |
| MNQ | $2/pt | 0.25 pts = $0.50 | 40–80 pts ($80–$160) | ~$1,700 |
| MCL | $100/pt | 0.01 = $10 | per barrel | ~$500 |
