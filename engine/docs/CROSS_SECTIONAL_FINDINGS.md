# Cross-Sectional Momentum — Discovery Findings (2026-06-24)

New strategy class (R3): dollar-neutral long-top / short-bottom across a basket,
orthogonal to the exhausted intraday-simple class, pairwise relative-value spreads,
and the turn-of-month calendar. Machinery: `analysis/cross_sectional.py`,
`backtest/xs_portfolio_backtester.py`, `scripts/run_discovery_cross_sectional.py`
(32 tests). Promotion requires gate-v2 **PASS** AND chronological H1/H2 **STRONG**.

## Result: NEGATIVE — no combo clears gate-v2.

Data: 6-ETF basket (SPY, QQQ, IWM, GLD, USO, XLE), daily, 2015-01-01 → 2026-03-27,
2,824 inner-joined bars (via yfinance — no micro-futures daily cache exists; Polygon
blocklists futures since the 2026-04-16 incident). Cost 2 bps/turnover.

### Default daily-rebalance grid (the committed driver): 0/6 promoted
Best (lookback 40, top_k 1): PF 1.05, ret +81%, DD 35% — but gate FAILs all 4 core
criteria (pf_ci_lower 0.94, p_edge 0.80, mc_dd 84%, dsr 0.0). Daily rebalance =
crushing turnover; the 10-bar lookbacks fail the split too.

### Lower-turnover probe (weekly / monthly hold) — best near-miss, still FAIL
| lookback | hold | top_k | n | PF | DD% | pf_ci_lo | p_edge | mc_dd | dsr | gate |
|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 20 (monthly) | 1 | 140 | 1.38 | 32.5 | 0.976 | 0.923 | 49.1 | **0.900** | FAIL |
| 40 | 5 (weekly) | 1 | 556 | 1.13 | 24.6 | 0.930 | 0.843 | 72.1 | 0.000 | FAIL |
| 40 | 5 (weekly) | 2 | 556 | 1.10 | 30.6 | 0.810 | 0.772 | 53.1 | 0.000 | FAIL |

The monthly lb=20 variant is the **most interesting near-miss**: DSR 0.90 and
p_edge 0.92 say it is *not* pure selection noise, and it passes the chronological
H1/H2 split (H1 PF 1.08, H2 PF 1.01 — both profitable). But it FAILs on two binding
criteria: **pf_ci_lower 0.976 < 1.10** (the bootstrap PF interval straddles 1.0, so
the edge is not statistically distinguishable from none at the lower bound) and
**mc_95th_dd 49% >>> 6%** (an unhedged, un-vol-targeted long/short book).

## Why not keep tuning (the discipline call)
Risk-scaling to a 6% DD budget shrinks the already-marginal return proportionally
(PF unchanged) → ~1.6%/yr on the monthly variant. And pf_ci_lower < 1.10 is a
sample/edge-strength wall, not a sizing wall — sizing cannot lift it (cf. the
2026-06-24 drawdown-attack refutation: sizing is not a valid lever for a non-edge).
The honest verdict: simple price-momentum cross-section on this daily ETF basket has
no deployable edge. Logged as a negative, like intraday-simple exhaustion.

## What remains genuinely untested (future arc, not this deliverable)
- Volatility-targeted / risk-parity sizing (would cut DD but not raise pf_ci_lower).
- Vol-adjusted or residual (beta-stripped) momentum signals.
- The intended micro-futures basket once a daily futures cache exists.
- A wider basket (more cross-sectional breadth → potentially stronger ranks).

The machinery is permanently available to test these the moment they're warranted;
no pre-registration / dark track stood up (T16) because there is no edge to track.
