# Research driver for docs/2026-09-27_vol_estimator_lookahead_audit.md — not engine code.
# ruff: noqa: E731, C408, B023
import contextlib
import io
import json
import sys

sys.path.insert(0, "/home/user/workspace/jarvis-repo-fresh")
import numpy as np
import pandas as pd
from engine.strategy_c import engine_v2 as E
from engine.strategy_c.engine_v2 import StrategyCConfigV2, StrategyCEngineV2

END = "2026-09-25"
SCALE_COST_BPS = 2.0
orig = StrategyCEngineV2._compute_returns_v2


def lagged(
    self, wp, sig, vol_scale, vix_mult, kalman_mult, cot_mult, daily_prices, initial_capital
):
    sh = lambda s: s.shift(1).fillna(1.0 if s is not vol_scale else float(s.iloc[0]))
    if self.rp_sizer:
        f = self.rp_sizer.size_portfolio
        if not getattr(f, "_lagged", False):

            def g(a, dp, as_of):
                return f(a, dp, as_of - pd.Timedelta(days=7))

            g._lagged = True
            self.rp_sizer.size_portfolio = g
    eq, al = orig(
        self,
        wp,
        sig,
        sh(vol_scale),
        sh(vix_mult),
        sh(kalman_mult),
        sh(cot_mult),
        daily_prices,
        initial_capital,
    )
    # charge scale turnover on the equity sleeve
    r = eq.pct_change().fillna(0.0)
    cost = al["combined_scale"].diff().abs().fillna(0.0) * SCALE_COST_BPS / 1e4
    r.loc[cost.index] -= cost.values
    eq2 = (1 + r).cumprod() * initial_capital
    eq2.iloc[0] = initial_capital
    return eq2, al


variants = {
    "A_legacy_5d": dict(vol_lookback_days=5, blend_fast_weight=1.0, winsorize_sigma=None),
    "B_legacy_10d": dict(vol_lookback_days=10, blend_fast_weight=1.0, winsorize_sigma=None),
    "C_blend_nowins": dict(vol_lookback_days=10, blend_fast_weight=0.40, winsorize_sigma=None),
    "D_blend_wins_LIVE": dict(vol_lookback_days=10, blend_fast_weight=0.40, winsorize_sigma=3.0),
    "E_pure21d_wins": dict(vol_lookback_days=10, blend_fast_weight=0.0, winsorize_sigma=3.0),
}
mode = sys.argv[1] if len(sys.argv) > 1 else "lagged"
if mode == "lagged":
    StrategyCEngineV2._compute_returns_v2 = lagged
base = None
curves = {}
out = {}
for name, kw in variants.items():
    eng = StrategyCEngineV2(StrategyCConfigV2(**kw))
    if base is None:
        with contextlib.redirect_stdout(io.StringIO()):
            eng.load_data()
        base = (eng._weekly_prices, eng._daily_prices, eng._weekly_vix)
    else:
        eng._weekly_prices, eng._daily_prices, eng._weekly_vix = base
    with contextlib.redirect_stdout(io.StringIO()):
        r = eng.run_backtest(end=END, label=name)
    eq = r["equity_curve"]
    curves[name] = eq
    m = eng._compute_metrics(eq)
    oos = eng._compute_metrics(eq.loc[E.OOS_START :])
    is_ = eng._compute_metrics(eq.loc[: E.IS_END])

    def win(a, b):
        e = eq.loc[a:b]
        return round(float((e / e.cummax() - 1).min() * 100), 2)

    out[name] = dict(
        full=m,
        is_=is_,
        oos=oos,
        dd_2018Q4=win("2018-10-01", "2018-12-31"),
        dd_2020=win("2020-02-15", "2020-04-30"),
        dd_2022=win("2022-01-01", "2022-12-31"),
        dd_2025=win("2025-02-15", "2025-05-31"),
    )
    print(
        f"{name:18s} Sh {m['sharpe']:.3f} CAGR {m['cagr']:5.2f} MDD {m['max_dd_pct']:6.2f} Calmar {m['calmar']:.2f} | IS Sh {is_['sharpe']:.2f} OOS Sh {oos['sharpe']:.2f} OOS MDD {oos['max_dd_pct']:.2f} | DD 18Q4 {out[name]['dd_2018Q4']} 2020 {out[name]['dd_2020']} 2022 {out[name]['dd_2022']} 2025 {out[name]['dd_2025']}"
    )
json.dump(out, open(f"results_{mode}.json", "w"), indent=2, default=str)
pd.DataFrame(curves).to_csv(f"curves_{mode}.csv")
rng = np.random.default_rng(7)


def boot(a, b):
    ra = curves[a].pct_change().dropna()
    rb = curves[b].pct_change().dropna()
    ix = ra.index.intersection(rb.index)
    ra, rb = ra[ix].values, rb[ix].values
    n = len(ix)
    L = 8
    d = []
    for _ in range(2000):
        s = rng.integers(0, n - L, size=n // L + 1)
        ii = np.concatenate([np.arange(x, x + L) for x in s])[:n]
        d.append(
            rb[ii].mean() / rb[ii].std() * np.sqrt(52) - ra[ii].mean() / ra[ii].std() * np.sqrt(52)
        )
    d = np.array(d)
    return f"{b} - {a}: {d.mean():+.3f} CI95 [{np.percentile(d,2.5):+.3f},{np.percentile(d,97.5):+.3f}] P>0 {(d>0).mean():.2f}"


for a, b in [
    ("B_legacy_10d", "D_blend_wins_LIVE"),
    ("A_legacy_5d", "D_blend_wins_LIVE"),
    ("C_blend_nowins", "D_blend_wins_LIVE"),
]:
    print(boot(a, b))
