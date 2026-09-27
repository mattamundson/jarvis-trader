# Strategy C+ — Vol Estimator Ablation, Lookahead Finding, Monitor Audit

Date: 2026-09-27 · Window: 2017-03-06 → 2026-09-25 (498 weekly bars) · Engine: `engine_v2` full stack, only the vol estimator varied.
Harness: `yfinance` auto-adjusted closes; Sharpe is raw (not excess of RF), same convention as `_compute_metrics`.

## 1. Headline: the backtest has a one-week lookahead

`run_backtest` computes vol scale, VIX multiplier, Kalman multiplier and risk-parity weights from data **through Friday t**, then applies them to `weekly_returns[t]` = the **Fri(t-1) → Fri(t)** return. The overlay sees the week it sizes. Live execution (signal Friday, fill Monday open) cannot do this.

Step-wise decomposition on the live config (D):

| Step | Sharpe | CAGR | MDD |
|---|---|---|---|
| As built (no lag) | 1.350 | 9.49% | -7.68% |
| + lag vol scale 1w | 1.045 | 7.45% | -7.80% |
| + lag VIX multiplier | 0.645 | 4.60% | -10.69% |
| + lag Kalman | 0.613 | 4.37% | -10.80% |
| + lag risk parity | 0.563 | 3.96% | -10.88% |
| + 2 bps cost on scale turnover | 0.552 | 3.88% | -10.92% |

Passive references, same window: static 40 SPY / 60 SHY Sharpe 1.03, CAGR 7.2%, MDD -12.6% at the same ~7% vol. SPY Sharpe 0.89, MDD -31.8%.

**Implication:** the realistic Strategy C+ does not beat a static 40/60 on Sharpe or CAGR. Its only remaining edge is a slightly smaller MDD (-10.9% vs -12.6%). The June "Sharpe 1.42 / 9 of 10 gates" promotion rested on the biased harness.

Fix shipped: `StrategyCConfigV2(overlay_lag_weeks=1)` (default). Set it to `0` to reproduce the legacy numbers. Verified: lag=1 → Sharpe 0.563, lag=0 → 1.350 (exact match with the harness).

## 2. Blended 40/60 vol estimator — Sharpe and MDD impact

| Variant | Full Sharpe | CAGR | MDD | Calmar | IS Sharpe | OOS Sharpe | DD 2020 | DD 2022 | DD 2025 |
|---|---|---|---|---|---|---|---|---|---|
| A legacy 5d | 0.493 | 3.73% | -12.27% | 0.30 | 0.30 | 0.66 | -7.68 | -7.37 | -5.88 |
| B legacy 10d | 0.493 | 3.51% | -10.99% | 0.32 | 0.32 | 0.64 | -8.41 | -7.19 | -6.11 |
| C blend 40/60, no winsorize | 0.541 | 3.69% | -10.85% | 0.34 | 0.50 | 0.59 | -7.32 | -7.15 | -6.31 |
| **D blend 40/60 + 3σ winsorize (LIVE)** | **0.552** | **3.88%** | **-10.92%** | **0.36** | 0.44 | 0.65 | -7.47 | -6.84 | -6.33 |
| E pure 21d + winsorize | 0.565 | 3.92% | -10.96% | 0.36 | 0.53 | 0.60 | -6.98 | -7.26 | -6.44 |

Block-bootstrap (8-week blocks, 2,000 draws) Sharpe differences:
- D − B (legacy 10d): **+0.057**, 95% CI [-0.071, +0.190], P(>0) 0.79
- D − A (legacy 5d): +0.031, CI [-0.189, +0.252], P(>0) 0.61
- D − C (winsorize effect): +0.011, CI [-0.036, +0.056], P(>0) 0.67

Read: the blend is directionally helpful (+0.06 Sharpe, and 1.35 pts less MDD than 5d) but **not statistically distinguishable** from legacy. Winsorization contributes almost nothing. Slower estimators rank monotonically better once lookahead is removed, because a fast 5d window gives up its biased "same-week" advantage. Without the lag, the ranking reverses (5d looked best at Sharpe 1.74), which is itself a symptom of the bias.

Recommendation: keep D (no reason to revert), but stop citing it as a Sharpe driver. The estimator is a second-order parameter; the strategy's problem is first-order (no edge vs a static 40/60 after the lag fix).

## 3. `signal_monitor.py` trigger audit — measured fire rates

| Trigger | v1 behavior | Fire rate | Verdict | v2 change |
|---|---|---|---|---|
| T1 RISK_ON & VIX ≥ 30 | warn | 1.5/yr | fine | kept |
| T2 RISK_ON & RealVol CRISIS | **CRITICAL** | 0.7/yr | false positive: scale was already compressed to mean 0.08 when it fired (2020-03, 2022-02/03, 2025-04/05) | CRITICAL only if scale > 1.25×(7%/RV); otherwise info |
| T3 RISK_ON & SHY > 85% | warn | 1.5/yr | redundant with T2 | info |
| T4 RISK_ON & fear > 0.7 | warn | **21.9/yr (42% of weeks)** | broken premise: median fear_score is 0.71. VIX > realized vol is the normal state (variance risk premium) | removed |
| T5 WoW \|Δ\|/prev > 30% | warn | **9.9/yr** | relative-only threshold explodes at low scale | \|Δscale\| ≥ 0.20 AND rel > 30% → 3.9/yr |
| T6 2σ z-bounds | warn | 0.7/yr | prior taken from the lookahead-biased v1 log; the live transition kept the stale bootstrap bounds (merge bug) | bounds = v2 lag-corrected p2.5/p97.5; recomputed from live history at ≥ 10 weeks |
| Healthy post | green embed every 6h | 28/week | alert fatigue | only the Sunday pre-market digest posts when healthy |
| Workflow exit capture | `echo $?` after python under `bash -e` | — | step died before capture, so exit_code was always blank | `set +e` |

Other v1 defects: history deduped on `effective_date`, which is the run date rather than the signal week, so a re-run on Saturday created a phantom week (now keyed on `week_of`). And the workflow sat on a non-default branch, so it never ran once (see section 4).

## 4. Why nothing ran June → September

1. `signal-monitor.yml`, `health-check.yml`, `deploy-dashboard.yml` and `deploy-engine.yml` exist only on `deploy/dashboard`. GitHub only runs `schedule:` from the default branch (`master`). None of them is registered in the repo's workflow list.
2. The Perplexity weekly signal cron (646a49fe) no longer exists. The last live signal before today was 2026-06-26, and `signal_history.json` still held 1 row.
3. `master` is 4,810 commits ahead of `deploy/dashboard` and has none of the v2 engine, risk_controls, transaction_costs or monitor code. `deploy/dashboard` lacks master's Strategy C security fixes (the live IB account ID lookup and the API key read from env).
