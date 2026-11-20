# Research driver: monitor baseline + trigger fire rates on the corrected v1 production engine.
# ruff: noqa: E731, C408, B023
import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from engine.strategy_c.engine import StrategyCConfig, StrategyCEngine  # noqa: E402

END = "2026-09-25"
# Start 53 weeks early so the momentum WARMUP rows (100% SHY) precede the
# comparison window instead of sitting inside it. save_results=False: v1's saver
# calls get_live_signal() and would overwrite output/strategy_c_plus_live_signal.json.
WARMUP_START = "2016-02-26"
cfg = StrategyCConfig(
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
    overlay_lag_weeks=0,
)
# lag=0 on purpose: the monitor sees same-Friday signal values (scale_t with RV_t).
# The 1w lag only matters for return attribution, not for what the signal shows.
e = StrategyCEngine(cfg)
with contextlib.redirect_stdout(io.StringIO()):
    r = e.run_backtest(start=WARMUP_START, end=END, save_results=False)
al = (
    r["allocation_log"]
    if isinstance(r["allocation_log"], pd.DataFrame)
    else pd.DataFrame(r["allocation_log"])
)
if "date" in al.columns:
    al = al.set_index("date")
al.index = pd.to_datetime(al.index)
al = al.loc["2017-03-17":]
s = al["combined_scale"].astype(float)
vs = al["vol_scale"].astype(float)
m = r.get("metrics") or r.get("full_metrics") or {}
print(
    "(signal-value replay, lag=0) metrics:",
    {k: m.get(k) for k in ("sharpe", "cagr", "max_dd_pct")} if m else list(r.keys()),
)

# realized vol + VIX layers for trigger replay
rv = (8.0 / vs.clip(lower=1e-6)).clip(upper=200)  # rv implied by vol_scale where scale<1
wv = e._weekly_vix.reindex(s.index).ffill()
vx = e.vix_composite.compute(e._weekly_vix, None) if False else None
regime = al["risk_regime"].astype(str)
ro = regime.str.startswith("RISK_ON")
n = len(s)
d = s.diff().abs()
rel = d / s.shift(1).replace(0, np.nan)
vt = e.vol_targeter
rv_true = []
for dt in s.index:
    try:
        rv_true.append(vt.compute_realized_vol(e._daily_prices["SPY"], e._daily_prices["QQQ"], dt))
    except Exception:
        rv_true.append(np.nan)
rv_true = pd.Series(rv_true, index=s.index)
crisis = rv_true >= 30
exp_max = (8.0 / rv_true).clip(upper=1.0) * 1.25
recent = s.loc["2024-09-27":]
recent_vs = vs.loc["2024-09-27":]


def st(x):
    q = x.quantile([0.025, 0.05, 0.5, 0.95, 0.975])
    return {
        "mean": round(x.mean(), 4),
        "sd": round(x.std(), 4),
        "p2_5": round(q[0.025], 4),
        "p5": round(q[0.05], 4),
        "p50": round(q[0.5], 4),
        "p95": round(q[0.95], 4),
        "p97_5": round(q[0.975], 4),
    }


pr = st(recent)
full = st(s)
d_p = float(d.dropna().quantile(0.975))
d_p95 = float(d.dropna().quantile(0.95))
print(
    f"|dscale| p95={d_p95:.3f} p97.5={d_p:.3f}; full-history scale p2.5={full['p2_5']} p97.5={full['p97_5']}"
)
rates = {
    "T1 RISK_ON & VIX>=30": int((ro & (wv >= 30)).sum()),
    "T2 CRISIS & vol scale NOT compressed (critical)": int((ro & crisis & (vs > exp_max)).sum()),
    "T2 CRISIS & vol scale compressed (info)": int((ro & crisis & (vs <= exp_max)).sum()),
    "T5 v1 rule rel>30%": int((rel > 0.30).sum()),
    "T5 v2 rule |d|>=0.20 & rel>30%": int(((d >= 0.20) & (rel > 0.30)).sum()),
    "T6 outside p2.5/p97.5 (2y prior)": int(((s < pr["p2_5"]) | (s > pr["p97_5"])).sum()),
    "T6 outside p2.5/p97.5 (full history)": int(((s < full["p2_5"]) | (s > full["p97_5"])).sum()),
    "T5 |d|>=p97.5": int((d >= d_p).sum()),
    "T5 |d|>=0.30": int((d >= 0.30).sum()),
}
yrs = n / 52
print(f"{n} weeks")
for k, v in rates.items():
    print(f"  {k:45s} {v:3d}  ~{v / yrs:.1f}/yr")
base = {
    "source": "engine.py v1, production live_signal config; same-Friday signal values (overlay_lag_weeks=0 — lag affects returns, not signal values)",
    "window": f"{s.index[0].date()} to {s.index[-1].date()} ({len(s)}w); recent_2y from {recent.index[0].date()}",
    "note": "combined_scale p97.5 equals the 1.1 cap, so T6 is effectively a low-side check",
    "priors": {"combined_scale": full, "combined_scale_recent_2y": pr, "vol_scale": st(vs)},
    "wow_abs_threshold": round(d_p, 4),
    "dscale_abs": st(d.loc["2024-09-27":].dropna()),
    "trigger_fire_counts_full_history": rates,
    "weeks_full_history": n,
}
out = Path(__file__).resolve().parents[2] / "output" / "signal_baseline.json"
out.write_text(json.dumps(base, indent=2))
print("wrote", out)
