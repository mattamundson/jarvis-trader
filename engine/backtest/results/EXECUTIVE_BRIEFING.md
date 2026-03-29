# JARVIS TRADER -- Executive Strategy Briefing
*Generated: 2026-03-29 | Strategy: STC (Schaff Trend Cycle) + ATR Stops/Targets + Regime Filter*

## The Verdict: CONDITIONAL GO (Paper Trading)

The STC-based strategy shows a real but narrow edge concentrated in **two instruments**. After fixing 8+ backtesting bugs (look-ahead bias, incorrect exit logic, EOD handling, target calculation errors), the reported Sharpe and PF numbers dropped dramatically from the original inflated figures. What remains is a modest, tradeable edge in micro gold daily and micro Nasdaq hourly -- not the home run the pre-bugfix numbers suggested, but honest numbers worth paper-trading.

---

## Corrected Performance (Fully Validated)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | MC Verdict | Sensitivity | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|------------|-------------|--------|
| 1 | MGC | 1d | 47 | 48.9 | 2.60 | 2.04 | +34.4% | 3.0% | EXCELLENT | N/A | PAPER TRADE |
| 2 | MNQ | 1h | 51 | 49.0 | 1.51 | 0.14 | +12.8% | 5.3% | EXCELLENT | 94/100 | PAPER TRADE |
| 3 | MCL | 1h | 29 | 62.1 | 1.89 | 0.05 | +8.5% | 5.1% | EXCELLENT | 85/100 | PAPER TRADE |
| 4 | SPY | 1h | 23 | 65.2 | 3.00 | -1.55 | +0.7% | 5.0% | EXCELLENT | 95/100 | HOLD |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). All returns gross of commissions.*

---

## Walk-Forward Validation (Out-of-Sample Edge)

| Symbol | TF | Windows | OOS Profitable | Avg OOS Return | WFE | Avg OOS PF | Verdict |
|--------|-----|---------|----------------|----------------|------|------------|---------|
| MGC | 1d | 7 | 3/7 (43%) | +2.7% | +0.27 | 1.60 | POSITIVE EDGE -- best WFE |
| MNQ | 1h | 6 | 3/6 (50%) | +4.8% | +0.24 | 0.97 | MARGINAL -- high variance |
| MCL | 1h | 6 | 2/6 (33%) | -1.0% | -0.16 | 0.80 | WEAK -- edge degrades OOS |
| MES | 1h | 6 | 1/6 (17%) | -1.4% | -0.17 | 0.71 | FAIL -- no OOS edge |
| SPY | 1h | 6 | 2/6 (33%) | -0.1% | -1.11 | 1.00 | FAIL -- overfit confirmed |

**Key finding:** Only MGC 1d carries a walk-forward efficiency above zero. MNQ 1h is marginal but retains positive average OOS returns (+4.8%). MCL and SPY show WFE decay suggesting parameter overfit.

---

## What to Trade (Priority Order)

1. **MGC 1d (Micro Gold Daily)** -- Strongest overall profile. PF 2.60, Sharpe 2.04, +34.4% return with only 3.0% max drawdown. Walk-forward WFE of +0.27 confirms real out-of-sample edge. Gold's trending behavior suits STC well on daily timeframes.

2. **MNQ 1h (Micro Nasdaq Hourly)** -- Highest trade count (51), +12.8% return, positive WFE (+0.24). Sensitivity score 94/100 means the edge is not parameter-fragile. Carries higher drawdown risk (5.3%) and OOS PF below 1.0 -- size conservatively.

3. **MCL 1h (Micro Crude Hourly)** -- Decent in-sample (PF 1.89, 62% WR) but walk-forward shows edge degradation (WFE -0.16). Use smaller size or wait for more OOS data. Optimizer consensus wants tighter stop (0.50 ATR) than default.

4. **SPY 1h (Equity Index Hourly)** -- On hold. Excellent in-sample sensitivity (95/100) and PF 3.00 but near-zero absolute return (+0.7%) and negative WFE (-1.11). Use as a signal-confirmation overlay for MES/MNQ rather than standalone.

---

## What NOT to Trade

| Symbol | TF | PF | Return | Reason |
|--------|-----|----|--------|--------|
| M2K | 1h | 0.64 | -3.1% | Consistently losing; only 27% win rate, 15 trades |
| M2K | 1d | 0.60 | -4.2% | Negative both timeframes -- Russell unsuitable for STC |
| MCL | 1d | 0.21 | -5.3% | Catastrophic PF; zero targets hit on daily crude |
| MES | 1h | 0.96 | -0.4% | WF shows 1/6 OOS profitable; no edge survives validation |
| MES | 1d | 0.75 | -3.6% | 36/51 trades exit at EOD -- targets unreachable on daily |
| MNQ | 1d | 0.79 | -2.6% | 43/57 EOD exits; daily NQ too volatile for intraday targets |
| MGC | 1h | 0.77 | -2.8% | Gold works daily only; hourly generates losing signals |

---

## Optimal Parameters Per Instrument

| Param | MGC 1d | MNQ 1h | MCL 1h | SPY 1h |
|-------|--------|--------|--------|--------|
| STC_OS | 17 | 15 | 23 | 15 |
| STC_OB | 88 | 92 | 83 | 88 |
| Stop ATR | 0.30 | 0.70 | 0.50 | 0.30 |
| T1 ATR | 1.50 | 1.00 | 1.00 | 1.00 |
| Regime Filter | ON | ON | ON | ON |

**Critical:** The current `signals.py` uses one global parameter set (STC_OS=15, STC_OB=83, Stop=0.70, T1=1.00). Per-instrument profiles must be implemented before paper trading (US-007).

---

## Risks and Caveats

1. **Monte Carlo is misleading.** All four MC verdicts read "EXCELLENT" with 100% probability profitable, but MC resamples from realized trades -- it cannot detect regime change or parameter overfit. The walk-forward results are the honest measure, and they are weaker.

2. **Walk-forward efficiency is marginal.** Even the best instrument (MGC 1d) only shows 3/7 OOS windows profitable. This is a fragile edge that could disappear in a different volatility regime.

3. **Sample size is thin.** MGC 1d has 47 trades over ~15 months. MNQ 1h has 51. Neither meets the 100+ trade threshold most quants want before committing capital.

4. **Commissions not included.** All results are gross. MES/MNQ ~$0.47/side, MGC ~$1.25/side. On small accounts with tight edges, commissions will matter.

5. **Data quality risk.** MES 2025 daily was proxied from SPY returns (Yahoo rate-limited ES=F). Some hourly data may have gaps near market open/close.

---

## Immediate Next Steps

1. **Implement per-instrument parameter profiles (US-007).** The single biggest lever. Deploy MGC 1d (STC_OS=17, STC_OB=88, Stop=0.30, T1=1.50) and MNQ 1h (STC_OS=15, STC_OB=92, Stop=0.70, T1=1.00) as separate configs.

2. **Paper trade MGC 1d for 30 trading days.** It has the highest WFE, best risk-adjusted return, and lowest drawdown. Target: confirm PF > 1.5 and Sharpe > 1.0 on live paper fills before sizing up.

3. **Re-optimize every 90 days.** Walk-forward windows shift. Re-run optimizer + WF validation quarterly. If WFE drops below 0.20 on any instrument, pull it from the active book.

---

*Source data: 49 result files in `engine/backtest/results/`. Includes optimizer JSONs, corrected backtests, sensitivity analysis (3 instruments), Monte Carlo (4 instruments, 10k sims each), and walk-forward validation (5 instruments, 6-7 windows each).*
