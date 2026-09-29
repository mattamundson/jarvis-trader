# Research driver for docs/2026-09-28_strategy_c_benchmark_study.md — not engine code.
# ruff: noqa: E731, C408, B023
"""
Corrected Strategy C+ (v1 and v2, overlays lagged 1w) vs benchmark allocations.

Fairness rules
  * Every rule-based benchmark trades on information through Friday t-1 only.
  * Primary metric = excess return over SHY (SHY is the strategy's cash leg,
    so raw Sharpe flatters anything ~50% SHY — SHY alone has raw Sharpe ~1.2).
  * Vol-matched view: each benchmark is levered/de-levered with SHY to the
    strategy's realized vol, so CAGR and MDD compare like-for-like risk.
  * Costs: 2 bps per unit of weekly turnover for all rule-based benchmarks.
"""

import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from engine.strategy_c import engine as E1  # noqa: E402
from engine.strategy_c.engine_v2 import StrategyCConfigV2, StrategyCEngineV2  # noqa: E402

START, END = "2017-03-06", "2026-09-25"
COST = 2e-4
OUT = Path(__file__).parent

# ── Strategy C+ v2 (lag fix is in-engine: overlay_lag_weeks=1) ────────────────
v2 = StrategyCEngineV2(StrategyCConfigV2(overlay_lag_weeks=1))
with contextlib.redirect_stdout(io.StringIO()):
    r2 = v2.run_backtest(start=START, end=END)
wp = v2._weekly_prices.loc[START:END]
dp = v2._daily_prices
eq_v2 = r2["equity_curve"]

# ── Strategy C+ v1 = production live_signal config, native lag guard ─────────
v1 = E1.StrategyCEngine(
    E1.StrategyCConfig(
        vol_target=8.0,
        vol_lookback_days=10,
        vol_floor=6.0,
        vix_ma_period=26,
        vix_mom_period=4,
        vix_weights=(0.40, 0.25, 0.20, 0.15),
        mom_lookback_primary=52,
        top_n=2,
        use_factor_tilt=True,
        use_macro_filter=True,
        use_cot=False,
        overlay_lag_weeks=1,
    )
)
with contextlib.redirect_stdout(io.StringIO()):
    r1 = v1.run_backtest(end=END)
eq_v1 = r1["equity_curve"]

R = wp.pct_change()
shy = R["SHY"].fillna(0.0)


def run_weights(W: pd.DataFrame) -> pd.Series:
    """W indexed by week t = weights decided at Fri t, applied to week t+1."""
    W = W.reindex(R.index).ffill().fillna(0.0)
    Wl = W.shift(1).fillna(0.0)
    cols = [c for c in Wl.columns if c in R.columns]
    gross = (Wl[cols] * R[cols].fillna(0.0)).sum(axis=1)
    turn = W.diff().abs().sum(axis=1).shift(1).fillna(0.0)
    return (gross - COST * turn).iloc[1:]


def static(w: dict) -> pd.Series:
    return run_weights(pd.DataFrame([w] * len(R), index=R.index))


# Daily-based realized vol (21d, as of Friday) for vol-targeted benchmark
spy_d = np.log(dp["SPY"] / dp["SPY"].shift(1))
rv21 = (spy_d.rolling(21).std() * np.sqrt(252) * 100).reindex(R.index, method="ffill")
spy_200 = dp["SPY"].rolling(200).mean().reindex(R.index, method="ffill")
spy_px = wp["SPY"]
mom52 = wp.pct_change(52)

bench = {}
bench["SPY buy&hold"] = static({"SPY": 1})
bench["60/40 SPY/IEF"] = static({"SPY": 0.6, "IEF": 0.4})
bench["40/60 SPY/SHY"] = static({"SPY": 0.4, "SHY": 0.6})
bench["40/60 XLK/SHY"] = static({"XLK": 0.4, "SHY": 0.6})

# Simple vol target: SPY at 7% target / 21d RV, cap 1.0, rest SHY
s = (7.0 / rv21).clip(upper=1.0).fillna(0.5)
bench["SPY vol-target 7% (21d)"] = run_weights(pd.DataFrame({"SPY": s, "SHY": 1 - s}))

# 200d SMA timing: SPY above 200d → SPY else SHY
t = (spy_px > spy_200).astype(float)
bench["SPY 200d SMA timing"] = run_weights(pd.DataFrame({"SPY": t, "SHY": 1 - t}))

# GEM-style dual momentum (12m): best of SPY/EFA if > SHY 12m, else IEF
gem = pd.DataFrame(0.0, index=R.index, columns=["SPY", "EFA", "IEF"])
for d in R.index:
    m = mom52.loc[d]
    if np.isnan(m.get("SPY", np.nan)):
        continue
    best = "SPY" if m["SPY"] >= m["EFA"] else "EFA"
    gem.loc[d, best if m[best] > m["SHY"] else "IEF"] = 1.0
bench["Dual momentum GEM (12m)"] = run_weights(gem)

# Inverse-vol risk parity SPY/IEF (21d), no leverage
iv = {}
for tk in ("SPY", "IEF"):
    lr = np.log(dp[tk] / dp[tk].shift(1))
    iv[tk] = 1.0 / (lr.rolling(21).std().reindex(R.index, method="ffill"))
iv = pd.DataFrame(iv)
bench["Risk parity SPY/IEF"] = run_weights(iv.div(iv.sum(axis=1), axis=0))

strat = {"Strategy C+ v2 (corrected)": eq_v2.pct_change().dropna()}
if True:
    strat["Strategy C+ v1 (corrected)"] = eq_v1.pct_change().dropna()

allr = {**strat, **bench}
ix = None
for v in allr.values():
    ix = v.index if ix is None else ix.intersection(v.index)
ix = ix[ix >= pd.Timestamp("2017-03-17")]
shy_ix = shy.reindex(ix).fillna(0.0)
target_vol = float(strat["Strategy C+ v2 (corrected)"].reindex(ix).std() * np.sqrt(52))


def metrics(r: pd.Series) -> dict:
    r = r.reindex(ix).fillna(0.0)
    ex = r - shy_ix
    eq = (1 + r).cumprod()
    yrs = len(r) / 52
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    vol = r.std() * np.sqrt(52)
    return {
        "cagr": round(cagr * 100, 2),
        "vol": round(vol * 100, 2),
        "excess_sharpe": round(float(ex.mean() / ex.std() * np.sqrt(52)), 3),
        "excess_cagr": round(((1 + ex).prod() ** (1 / yrs) - 1) * 100, 2),
        "mdd": round(float(dd) * 100, 2),
        "calmar": round(float(cagr / abs(dd)), 3) if dd < 0 else None,
        "dd_2020": round(
            float(
                (
                    (1 + r.loc["2020-02-15":"2020-04-30"])
                    .cumprod()
                    .pipe(lambda e: e / e.cummax() - 1)
                ).min()
            )
            * 100,
            2,
        ),
        "dd_2022": round(
            float(
                (
                    (1 + r.loc["2022-01-01":"2022-12-31"])
                    .cumprod()
                    .pipe(lambda e: e / e.cummax() - 1)
                ).min()
            )
            * 100,
            2,
        ),
        "oos_excess_sharpe": round(
            float(
                (r.loc["2021-05-01":] - shy_ix.loc["2021-05-01":]).pipe(
                    lambda x: x.mean() / x.std() * np.sqrt(52)
                )
            ),
            3,
        ),
    }


def vol_match(r: pd.Series) -> pd.Series:
    r = r.reindex(ix).fillna(0.0)
    k = target_vol / (r.std() * np.sqrt(52))
    return shy_ix + k * (r - shy_ix)  # lever the excess over the cash leg


rows, rows_vm = {}, {}
for k, r in allr.items():
    rows[k] = metrics(r)
    rows_vm[k] = metrics(vol_match(r))

# Bootstrap excess-Sharpe difference: each strategy vs each other series (8w blocks)
rng = np.random.default_rng(11)
n, L = len(ix), 8
idxs = [
    np.concatenate([np.arange(a, a + L) for a in rng.integers(0, n - L, size=n // L + 1)])[:n]
    for _ in range(2000)
]
xsr = lambda x: x.mean() / x.std() * np.sqrt(52)
boot = {}
for sname in strat:
    xs = (allr[sname].reindex(ix).fillna(0) - shy_ix).values
    boot[sname] = {}
    for k, r in allr.items():
        if k == sname:
            continue
        xb = (r.reindex(ix).fillna(0) - shy_ix).values
        d = np.array([xsr(xs[i]) - xsr(xb[i]) for i in idxs])
        boot[sname][k] = {
            "mean": round(float(d.mean()), 3),
            "ci95": [
                round(float(np.percentile(d, 2.5)), 3),
                round(float(np.percentile(d, 97.5)), 3),
            ],
            "p_strategy_better": round(float((d > 0).mean()), 2),
        }

res = {
    "window": [str(ix[0].date()), str(ix[-1].date())],
    "weeks": len(ix),
    "target_vol_pct": round(target_vol * 100, 2),
    "raw": rows,
    "vol_matched": rows_vm,
    "bootstrap_strategy_minus_other_excess_sharpe": boot,
}
(OUT / "benchmarks_results.json").write_text(json.dumps(res, indent=2))

hdr = f"{'':30s} {'CAGR':>6s} {'Vol':>6s} {'xSharpe':>8s} {'xCAGR':>6s} {'MDD':>7s} {'Calmar':>7s} {'DD20':>7s} {'DD22':>7s} {'OOSxSh':>7s}"
for title, tab in (("RAW", rows), (f"VOL-MATCHED to {target_vol * 100:.2f}%", rows_vm)):
    print(f"\n=== {title} ===  {res['window']} ({len(ix)}w)\n{hdr}")
    for k, m in sorted(tab.items(), key=lambda kv: -kv[1]["excess_sharpe"]):
        print(
            f"{k:30s} {m['cagr']:6.2f} {m['vol']:6.2f} {m['excess_sharpe']:8.3f} {m['excess_cagr']:6.2f} {m['mdd']:7.2f} {m['calmar'] or 0:7.3f} {m['dd_2020']:7.2f} {m['dd_2022']:7.2f} {m['oos_excess_sharpe']:7.3f}"
        )
for sname, bb in boot.items():
    print(f"\n=== {sname} minus X, excess Sharpe (8w block bootstrap, 2000) ===")
    for k, b in sorted(bb.items(), key=lambda kv: kv[1]["mean"]):
        print(
            f"{k:30s} {b['mean']:+.3f}  CI95 [{b['ci95'][0]:+.3f}, {b['ci95'][1]:+.3f}]  P(better) {b['p_strategy_better']:.2f}"
        )
