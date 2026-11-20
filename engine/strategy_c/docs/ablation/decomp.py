# Research driver for docs/2026-09-27_vol_estimator_lookahead_audit.md — not engine code.
# ruff: noqa: E731, C408, B023
# These wrappers apply their own lags, so the native engine lag is set to 0 here.
import contextlib
import io
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4]))
import pandas as pd
from engine.strategy_c.engine_v2 import StrategyCConfigV2, StrategyCEngineV2

END = "2026-09-25"
orig = StrategyCEngineV2._compute_returns_v2


def make(lag_vol, lag_vix, lag_kal, lag_rp, cost):
    def f(self, wp, sig, vol_scale, vix_mult, kalman_mult, cot_mult, daily_prices, initial_capital):
        vs, vm, km, cm, dp, ic = (
            vol_scale,
            vix_mult,
            kalman_mult,
            cot_mult,
            daily_prices,
            initial_capital,
        )
        s = lambda x, on: x.shift(1).bfill() if on else x
        if lag_rp and self.rp_sizer and not getattr(self.rp_sizer.size_portfolio, "_l", False):
            g0 = self.rp_sizer.size_portfolio

            def g(a, d, t):
                return g0(a, d, t - pd.Timedelta(days=7))

            g._l = True
            self.rp_sizer.size_portfolio = g
        eq, al = orig(self, wp, sig, s(vs, lag_vol), s(vm, lag_vix), s(km, lag_kal), cm, dp, ic)
        if cost:
            r = eq.pct_change().fillna(0.0)
            c = al["combined_scale"].diff().abs().fillna(0) * 2e-4
            r.loc[c.index] -= c.values
            eq = (1 + r).cumprod() * ic
        return eq, al

    return f


eng0 = StrategyCEngineV2(StrategyCConfigV2(overlay_lag_weeks=0))
with contextlib.redirect_stdout(io.StringIO()):
    eng0.load_data()
base = (eng0._weekly_prices, eng0._daily_prices, eng0._weekly_vix)
steps = [
    ("0 as-built (no lag)", (0, 0, 0, 0, 0)),
    ("1 lag vol", (1, 0, 0, 0, 0)),
    ("2 +lag VIX", (1, 1, 0, 0, 0)),
    ("3 +lag Kalman", (1, 1, 1, 0, 0)),
    ("4 +lag risk-parity", (1, 1, 1, 1, 0)),
    ("5 +scale cost 2bps", (1, 1, 1, 1, 1)),
]
for lbl, a in steps:
    StrategyCEngineV2._compute_returns_v2 = make(*a)
    e = StrategyCEngineV2(StrategyCConfigV2(overlay_lag_weeks=0))
    e._weekly_prices, e._daily_prices, e._weekly_vix = base
    with contextlib.redirect_stdout(io.StringIO()):
        r = e.run_backtest(end=END)
    m = e._compute_metrics(r["equity_curve"])
    print(
        f"{lbl:24s} Sharpe {m['sharpe']:.3f} CAGR {m['cagr']:5.2f}% MDD {m['max_dd_pct']:6.2f}% vol {m['ann_vol']:.2f}%"
    )
wp = base[0].loc["2017-03-06":END]
for lbl, w in [
    ("SPY buy&hold", {"SPY": 1}),
    ("SHY buy&hold", {"SHY": 1}),
    ("static 40 SPY/60 SHY", {"SPY": 0.4, "SHY": 0.6}),
    ("static 40 XLK/60 SHY", {"XLK": 0.4, "SHY": 0.6}),
]:
    r = sum(wp[k].pct_change() * v for k, v in w.items()).dropna()
    eq = (1 + r).cumprod()
    m = eng0._compute_metrics(eq)
    print(
        f"{lbl:24s} Sharpe {m['sharpe']:.3f} CAGR {m['cagr']:5.2f}% MDD {m['max_dd_pct']:6.2f}% vol {m['ann_vol']:.2f}%"
    )
