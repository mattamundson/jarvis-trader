# Discovery Batch 1 — Daily-Timeframe Trend (2026-06-12)

**Question:** The full gate-v2 verdict ledger (38 verdicts) shows the only validated
edge is trend-following on MGC (gold) and MES (S&P), all at the **1-hour** timeframe.
Every other family — meanrev, donchian, ORB, gap, initial-balance, TPO, confluence,
VIX-filter — fails, most with `pf_ci_lower < 1.0`. The one lower-TF attempt
(`MES_trend_15m`) failed badly (mc_dd 23.6%). The textbook home of trend-following is
the *higher* timeframe (daily), which was **completely untested** — yet daily data goes
back to 2022 (4+ years). Does the proven SMA-trend recipe replicate/improve at the daily
timeframe?

**Method:** Reused the exact validated gate-v2 machinery from
`run_mgc_trend_rv_filter_rank1.py` (IS grid search → OOS walk-forward → fixed-params
sweep → cost sweep → gate computation). RV filter disabled for a pure trend read.
Daily 4yr CSVs (`MES_2022-01-01_2026-03-28_1d`, `MGC_2022-01-01_2026-03-28_1d`).
Runner: `run_daily_trend_discovery.py`. Fully offline; no IB, no engine, no live state.

## Result: BOTH FAIL — sample-starved, not edge-starved

| Symbol | Verdict | OOS trades | Full-sample trades (4yr) | Notes |
|--------|---------|-----------|--------------------------|-------|
| MES daily | FAIL | **0** | ~1–2 | trend signal barely fires on daily MES |
| MGC daily | FAIL | **3** (across 13 windows) | 8–14 | IS PFs spectacular, OOS collapses to 0 |

**The decisive evidence (MGC):** in-sample window PFs looked like a goldmine — 2.69, 5.33,
7.25, even `inf` and 70.32 — but those are computed on **1–5 trades per window**. Out of
sample, the same params produced **3 trades total across 13 windows, every one PF = 0.00**.
The apparent edge is pure overfitting on tiny samples; it evaporates the moment it's tested
forward. This is exactly the failure mode gate-v2 exists to catch.

## Why daily can't work here (the real constraint)

- SMA(50,200) daily fires only **2 entries in 4 years** (a position-and-hold system).
- Even the fastest tradeable daily periods (fast 5–10 / slow 20–40) yield just **8–14
  trades over the full 4 years** → ~2–4 OOS trades in a walk-forward split.
- Gate-v2 requires **≥30 OOS trades** across multiple windows. Daily over 4yr is
  categorically below that floor — by an order of magnitude.
- Note: the signal generator's RV annualization is hourly-calibrated (reads ~73% on daily
  gold; daily √252 vs hourly √(24·252)), confirming the whole signal stack is tuned for 1h.

**Conclusion:** Higher-TF (daily) trend is a **dead end on the available data** — not
because gold/equity don't trend, but because daily bars over 4 years cannot generate the
trade density gate-v2 requires, and the OOS evidence shows the in-sample "edge" is overfit.
Validating daily trend would need **10–20 years of daily history** (not cached). The 1-hour
timeframe remains the only place with enough trade density to validate an edge.

## Strategic implication for "systematic strategy discovery"

Combined with the verdict-ledger analysis (12 strategy families × 5 instruments, all at 1h,
only trend on MGC/MES survives), this batch closes the last obvious unexplored frontier with
evidence. **The binding constraint on new edge is DATA (longer history / more instruments),
not strategy ideas.** Generating more candidate families on the current cached 1h data is
low-ROI — that ground is salted. The highest-ROI moves are now:

1. **Harden + accumulate forward-test evidence** on the ~5 existing edges (the natural pivot).
2. To unlock genuinely new edge: acquire **longer daily history** (makes higher-TF testable)
   or add **new instruments with 1h data** (deferred — instrument expansion is option 4).

Reproduce: `API_KEY=offline-dummy .venv/Scripts/python.exe backtest/run_daily_trend_discovery.py`
(verdicts written to `data/gate_v2_verdicts/{MES,MGC}_trend_daily_rank1.json`, gitignored).
