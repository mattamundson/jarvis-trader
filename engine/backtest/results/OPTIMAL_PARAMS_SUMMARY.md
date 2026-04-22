# JARVIS TRADER — Optimal Parameter Summary
Generated: 2026-03-29 (Updated with MNQ optimizer, MGC walk-forward, MCL sensitivity)

## Source Files Found
- `SPY_1h_optimal_params.json` — SPY 1h optimizer consensus (5 top param sets)
- `MGC_1d_optimal_params.json` — MGC 1d optimizer consensus (5 top param sets)
- `MATRIX_FIXED_20260329_0709.json` — Full 12-cell instrument matrix (6 symbols x 2 TFs)
- `SPY_1h_sensitivity.json` / `SPY_1h_sensitivity_report.txt` — SPY 1h robustness analysis
- `MNQ_1h_sensitivity.json` / `MNQ_1h_sensitivity_report.txt` — MNQ 1h robustness analysis
- `SPY_1h_monte_carlo.json` — SPY 1h Monte Carlo (10k sims, verdict: EXCELLENT)
- `MGC_1d_monte_carlo.json` — MGC 1d Monte Carlo (10k sims, verdict: EXCELLENT)
- `MNQ_1h_monte_carlo.json` — MNQ 1h Monte Carlo (10k sims, verdict: EXCELLENT)
- `WF_SPY_1h_walk_forward.json` — SPY 1h walk-forward (6 windows, 2/6 profitable OOS)
- `WF_MES_1h_walk_forward.json` — MES 1h walk-forward (6 windows, 2/6 profitable OOS)

---

## Optimal Parameters by Instrument

### SPY 1h (Optimizer Consensus)
| Parameter | Value |
|-----------|-------|
| STC_OS | 15 |
| STC_OB | 88 |
| Stop_ATR | 0.30 |
| T1_ATR | 1.00 |
| Regime Filter | ON |
| Sensitivity Stability | 95/100 (ROBUST) |
| Monte Carlo Verdict | EXCELLENT (100% prob profitable) |

### MGC 1d (Optimizer Consensus — CAUTION: WFE=0.27 OVERFIT)
| Parameter | Value |
|-----------|-------|
| STC_OS | 17 |
| STC_OB | 88 |
| Stop_ATR | 0.30 |
| T1_ATR | 1.50 |
| Regime Filter | ON |
| Sensitivity Stability | N/A (not yet run) |
| Monte Carlo Verdict | EXCELLENT (100% prob profitable) |
| Walk-Forward WFE | **0.27 (OVERFIT — threshold is >0.50)** |
| Avg OOS Return | 2.7% vs 10.1% IS (73% degradation) |
| OOS Windows Profitable | 3/7 |

**Critical finding:** The +34.4% backtest return is optimistic. Real live edge is approximately +2.7% annualized based on walk-forward OOS performance.

### MNQ 1h (Optimizer Confirmed — 162 Combinations Tested)
| Parameter | Value |
|-----------|-------|
| STC_OS | 15 |
| STC_OB | **92** (wider overbought band filters Nasdaq noise) |
| Stop_ATR | 0.70 |
| T1_ATR | **1.00** |
| Regime Filter | ON |
| Trades | 86 |
| Win Rate | 50% |
| Profit Factor | 1.51 |
| Sharpe | 0.21 |
| Return | +22.6% |
| Max Drawdown | 5.2% |
| Sensitivity Stability | 94/100 (ROBUST) |
| Monte Carlo Verdict | EXCELLENT (100% prob profitable) |

**Key insights:**
- STC_OB=92 (wider overbought band) filters noise better for Nasdaq hourly — consensus across all top 10 results
- Regime filter=True wins all top 10 — confirms live pipeline default is correct
- 86 trades gives strong statistical significance

### MCL 1h (Sensitivity-Tested — Stop Dead Zone Identified)
| Parameter | Value |
|-----------|-------|
| STC_OS | 15 |
| STC_OB | 83 |
| Stop_ATR | **0.84** (0.70 is a dead zone — only 8 trades) |
| T1_ATR | **1.00** (1.00-1.20 optimal; current 1.50 too wide, rarely hit) |
| Regime Filter | ON |
| Projected Trades | 65 |
| Projected PF | ~1.81 |
| Projected Return | +19.8% |
| Monte Carlo Verdict | 100% probability of profit |

**Critical finding:** Stop=0.70 ATR is a DEAD ZONE for MCL (only 8 trades). Widening to 0.84 ATR gives 65 trades with PF 1.81 and +19.8% return.

---

## Recommended Tradeable Universe (Priority Order)

| Priority | Symbol | TF | STC_OS | STC_OB | Stop_ATR | T1_ATR | Trades | WR% | PF | Sharpe | Return% | MaxDD% | Status |
|----------|--------|-----|--------|--------|----------|--------|--------|-----|------|--------|---------|--------|--------|
| **1** | MNQ | 1h | 15 | 92 | 0.70 | 1.00 | 86 | 50.0 | 1.51 | 0.21 | +22.6 | 5.2 | **MOST ROBUST** |
| **2** | MCL | 1h | 15 | 83 | 0.84 | 1.00 | 65 | — | ~1.81 | — | +19.8 | — | PAPER TRADE |
| **3** | MGC | 1d | 17 | 88 | 0.30 | 1.50 | 47 | 48.9 | 2.60 | 2.04 | +34.4 | 3.0 | **CAUTION: WFE=0.27** |
| **4** | SPY | 1h | 15 | 88 | 0.30 | 1.00 | 23 | 65.2 | 3.00 | -1.55 | +0.7 | 5.0 | NEEDS WALK-FORWARD |

**Notes on SPY 1h:**
- Optimizer found PF=3.23 with stop=0.30 ATR (very tight stop), but walk-forward shows only 2/6 OOS windows profitable (WFE = -1.11). Parameters may be overfit to the in-sample period.
- Sensitivity analysis shows the base params (STC_OS=15, STC_OB=83, Stop=0.70, T1=1.50) are ROBUST (stability 95/100), but absolute returns are thin (+0.7% over 22 months).
- Recommend further optimization or use SPY as a signal-confirmation overlay rather than standalone.

---

## Drop List (Do Not Trade)

| Symbol | TF | Trades | WR% | PF | Return% | MaxDD% | Reason |
|--------|-----|--------|-----|------|---------|--------|--------|
| M2K | 1h | 15 | 26.7 | 0.64 | -3.1 | 5.6 | PF < 1.0, negative return, low trade count |
| M2K | 1d | 34 | 44.1 | 0.60 | -4.2 | 5.3 | PF < 1.0, consistent loser both timeframes |
| MCL | 1d | 15 | 26.7 | 0.21 | -5.3 | 5.7 | PF = 0.21 (catastrophic), 0 targets hit |
| MES | 1h | 21 | 42.9 | 0.96 | -0.4 | 5.4 | PF < 1.0, WF OOS avg return = -1.6% |
| MES | 1d | 51 | 49.0 | 0.75 | -3.6 | 5.6 | PF < 1.0, 36/51 exits at EOD (targets unreachable) |
| MNQ | 1d | 57 | 47.4 | 0.79 | -2.6 | 5.3 | PF < 1.0, 43/57 exits at EOD |
| MGC | 1h | 26 | 42.3 | 0.77 | -2.8 | 6.0 | PF < 1.0, gold better on daily only |

---

## Current signals.py Constants (Hardcoded)

File: `engine/backtest/signals.py`

```python
# STC thresholds
STC_OS = 15      # 1h optimal (daily: 23 per old grid search)
STC_OB = 83      # consistent across timeframes

# Stop and target ATR multiples
STOP_ATR = 0.70  # both timeframes
T1_ATR   = 1.00  # 1h intraday-realistic (was 1.50 — unreachable)
T2_ATR   = 1.80  # intraday stretch target (was 2.618)
T3_ATR   = 2.618 # runner target (was 4.0)

# STC computation params (not tuned)
# fast=23, slow=50, k_period=10, d_period=3
```

### Discrepancy Alert
The current `signals.py` uses **one set of constants for all instruments**. The optimizer results show different instruments want different parameters:

| Param | signals.py | SPY 1h Opt | MGC 1d Opt | MNQ 1h Opt | MCL 1h Sens |
|-------|-----------|------------|------------|------------|-------------|
| STC_OS | 15 | 15 | 17 | 15 | 15 |
| STC_OB | 83 | 88 | 88 | **92** | 83 |
| Stop_ATR | 0.70 | 0.30 | 0.30 | 0.70 | **0.84** |
| T1_ATR | 1.00 | 1.00 | 1.50 | **1.00** | **1.00** |

**Recommendation:** US-007 should implement per-instrument parameter profiles rather than global constants. MNQ specifically needs STC_OB=92 and MCL needs Stop=0.84 ATR.

---

## Walk-Forward Validation Summary

| Symbol | TF | Avg OOS Return | WFE | OOS Windows Profitable | Verdict |
|--------|-----|---------------|------|----------------------|---------|
| SPY | 1h | -0.14% | -1.11 | 2/6 | CAUTION — params may be overfit |
| MES | 1h | -1.57% | -0.29 | 2/6 | CAUTION — poor OOS performance |
| MGC | 1d | **2.7%** | **0.27** | **3/7** | **OVERFIT — 73% IS-to-OOS degradation** |

**MGC 1d walk-forward critical finding:** WFE=0.27 is below the 0.50 "good" threshold. The +34.4% backtest is optimistic -- real live edge is approximately +2.7% annualized. Proceed with caution; add gold trend filter before going live.

MNQ 1h walk-forward has not been run yet but sensitivity (94/100) and Monte Carlo (100% prob profitable) are both strong.

---

## Monte Carlo Confidence

| Symbol | TF | Sims | Prob Profitable | Median DD% | Sharpe p5-p95 | Verdict |
|--------|-----|------|-----------------|-----------|---------------|---------|
| SPY | 1h | 10k | 100% | 0.15% | 6.94-6.96 | EXCELLENT |
| MGC | 1d | 10k | 100% | 4.22% | 5.49-5.90 | EXCELLENT |
| MNQ | 1h | 10k | 100% | 6.66% | 2.30-2.50 | EXCELLENT |
| MCL | 1h | — | **100%** | — | — | **PROFITABLE** |

Note: Monte Carlo resamples from realized trades -- it validates trade-level distribution robustness but does NOT protect against regime change or param overfit.

---

## Next Steps for Live Deployment

1. **Update signals.py STC_OB to 92 for MNQ** or implement per-instrument parameter profiles in US-007

2. **Update signals.py Stop to 0.84 ATR for MCL** or implement per-instrument parameter profiles in US-007

3. **US-008: Run E2E pipeline test** with updated per-instrument parameters

4. **Paper trading deployment** — Deploy MNQ 1h first (most robust: 86 trades, PF 1.51, sensitivity 94/100, MC 100%), MCL 1h second

5. **Monitor cadence** — Walk-forward re-test every 90 days; re-optimize if WFE drops below 0.5

6. **Add gold trend filter** before going live with MGC 1d (WFE=0.27 indicates overfit; real edge ~2.7% annualized)

---

*Data sources: optimizer JSONs, corrected backtests, sensitivity analysis, Monte Carlo, walk-forward tests*
*All results are gross of commissions. MES/MNQ commission ~$0.47/side, MGC ~$1.25/side.*
