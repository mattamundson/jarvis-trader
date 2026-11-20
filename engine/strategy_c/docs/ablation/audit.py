# Research driver for docs/2026-09-27_vol_estimator_lookahead_audit.md — not engine code.
# ruff: noqa: E731, C408, B023
# These wrappers apply their own lags, so the native engine lag is set to 0 here.
import contextlib
import io
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4]))
import numpy as np
import pandas as pd
from engine.strategy_c.engine_v2 import StrategyCConfigV2, StrategyCEngineV2

e = StrategyCEngineV2(StrategyCConfigV2(overlay_lag_weeks=0))
with contextlib.redirect_stdout(io.StringIO()):
    e.load_data()
    r = e.run_backtest(end="2026-09-25")
vol = r["vol_df"]
al = r["allocation_log"]
wv = e._weekly_vix.loc[vol.index.min() : vol.index.max()]
vx = e.vix_composite.compute(wv, vol["realized_vol"])
print("vix cols:", list(vx.columns))
df = (
    pd.DataFrame(
        {"rv": vol["realized_vol"], "scale": al["combined_scale"], "regime": al["risk_regime"]}
    )
    .join(vx, how="left")
    .dropna(subset=["scale"])
)
df["vol_regime"] = pd.cut(
    df.rv, [0, 10, 18, 30, 1e9], labels=["CALM", "NORMAL", "ELEVATED", "CRISIS"], right=False
)
vcol = [c for c in vx.columns if c.lower() in ("vix", "vix_level")][0]
df["vix_regime"] = pd.cut(
    df[vcol],
    [0, 12, 20, 30, 40, 1e9],
    labels=["CALM", "NORMAL", "CAUTION", "ELEVATED", "EXTREME"],
    right=False,
)
ro = df.regime.astype(str).str.startswith("RISK_ON")
n = len(df)
print("weeks", n, "RISK_ON weeks", int(ro.sum()))
fcol = [c for c in vx.columns if "fear" in c.lower()][0]
tr = {
    "T1 RISK_ON & VIX>=30 (warn)": ro & df.vix_regime.isin(["ELEVATED", "EXTREME"]),
    "T2 RISK_ON & RealVol CRISIS (CRITICAL)": ro & (df.vol_regime == "CRISIS"),
    "T3 RISK_ON & SHY>85% (warn)": ro & (df.scale < 0.15),
    "T4 RISK_ON & fear>0.7 (warn)": ro & (df[fcol] > 0.7),
    "T5 WoW scale chg >30% (warn)": (df.scale.diff().abs() / df.scale.shift(1).replace(0, np.nan))
    > 0.30,
    "T6 z-bound scale<0.0434 or >1.0146": (df.scale < 0.0434) | (df.scale > 1.0146),
}
fut = (e._weekly_prices["SPY"].pct_change(4).shift(-4)).reindex(df.index)
for k, m in tr.items():
    m = m.fillna(False)
    c = int(m.sum())
    fr = fut[m].mean() * 100 if c else float("nan")
    base = fut.mean() * 100
    print(
        f"{k:42s} fires {c:3d}/{n} ({c/n*100:4.1f}%) ~{c/n*52:4.1f}/yr | SPY next-4w when fired {fr:+.2f}% vs base {base:+.2f}%"
    )
print("fear pctiles:", df[fcol].quantile([0.1, 0.5, 0.9]).round(3).to_dict())
print(
    "T2 dates:",
    [d.strftime("%Y-%m-%d") for d in df.index[(ro & (df.vol_regime == "CRISIS")).fillna(False)]][
        :20
    ],
)
print(
    "T2 scale when fired:",
    df.scale[(ro & (df.vol_regime == "CRISIS")).fillna(False)].describe().round(3).to_dict(),
)
