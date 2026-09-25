#!/usr/bin/env python
"""
Impact quantification for validation defects #751 (IB) and #752 (VWAP).

READ-ONLY research audit. Implements step 1 of both issues' "Required
remediation" lists: quantify how far each defect moves the historical signals
and backtest metrics BEFORE anyone patches production behaviour. It does not
modify any production module, verdict file, or cache. The "causal" variants
below exist only inside this script as comparators.

#751 -- ``backtest/ib_signals.py::compute_initial_balance`` joins the completed
session IB onto every row of the calendar date, and masks only rows INSIDE the
IB window. Pre-open rows therefore carry the future IB. The leak reaches
decisions in ``ib_breakout_signals`` through the per-session ``_first_cross``
"fresh breakout" flag: a premarket close beyond the (future) IB consumes the
session's single fresh flag, so the RTH breakout that would have traded is
suppressed. The comparator here exposes the IB only on bars at/after the IB
window end.

#752 -- ``backtest/vwap_signals.py::generate_vwap_signals`` accumulates VWAP
across overnight bars and only blocks entries at hour >= 15 ET, so on the
near-continuous Globex 1h cache used by ``run_mes_vwap_rank1`` it can signal
and trade 00:00-08:59 ET. The comparator restricts input rows to RTH hours
(09:00-15:59 ET on 1h bars; the 09:00 bar is the session-reset bar the module
already treats as the open).

Usage (from engine/):
    .venv/Scripts/python scripts/audit_lookahead_defects_751_752.py [--json OUT]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

CACHE_DIR = ENGINE_ROOT / "backtest" / "cache"
IB_SYMBOLS = ("MES", "MGC")
IB_MODES = ("go", "fade")
RTH_OPEN_HOUR_ET = 9
RTH_LAST_HOUR_ET = 15


# ---------------------------------------------------------------------------
# #751 -- Initial Balance
# ---------------------------------------------------------------------------


def causal_initial_balance(df: pd.DataFrame, open_minutes: int = 60, **kwargs) -> pd.DataFrame:
    """Comparator: same output contract, but IB is NaN on every bar before the
    IB window has closed (premarket AND in-window)."""
    from backtest import ib_signals

    out = ib_signals.compute_initial_balance(df, open_minutes=open_minutes, **kwargs)
    tz = kwargs.get("tz", "America/Chicago")
    hour = kwargs.get("market_open_hour", 9)
    minute = kwargs.get("market_open_minute", 30)
    idx = out.index
    idx = idx.tz_convert(tz) if idx.tz is not None else idx.tz_localize(tz)
    mins_from_open = (idx.hour - hour) * 60 + (idx.minute - minute)
    post_ib = np.asarray(mins_from_open >= open_minutes)

    for col in ("ib_high", "ib_low", "ib_mid"):
        out[col] = out[col].where(post_ib)
    out["above_ib_high"] = out["close"] > out["ib_high"]
    out["below_ib_low"] = out["close"] < out["ib_low"]
    session = pd.Series(idx.date, index=out.index)

    def _first(s: pd.Series) -> pd.Series:
        return (s.cumsum() == 1) & s

    out["ib_high_fresh_breakout"] = out.groupby(session)["above_ib_high"].transform(_first)
    out["ib_low_fresh_breakout"] = out.groupby(session)["below_ib_low"].transform(_first)
    return out


@contextmanager
def _patched_ib(fn):
    from backtest import ib_breakout_signals

    original = ib_breakout_signals.compute_initial_balance
    ib_breakout_signals.compute_initial_balance = fn
    try:
        yield
    finally:
        ib_breakout_signals.compute_initial_balance = original


def premarket_leak_rows(df: pd.DataFrame, open_minutes: int) -> int:
    """Rows before the IB window opens that nonetheless carry a non-NaN IB."""
    from backtest import ib_signals

    out = ib_signals.compute_initial_balance(
        df, open_minutes=open_minutes, market_open_hour=8, market_open_minute=30,
        tz="America/Chicago",
    )
    idx = out.index.tz_convert("America/Chicago")
    pre = np.asarray(((idx.hour - 8) * 60 + (idx.minute - 30)) < 0)
    return int((out["ib_high"].notna().to_numpy() & pre).sum())


def audit_ib(symbol: str) -> list[dict]:
    from backtest import ib_wfo_runner as runner

    df = runner._load_data(CACHE_DIR / runner.SPECS[symbol]["data_file"])
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    rows = []
    for mode, tm, om in itertools.product(
        IB_MODES, runner.TARGET_MULT_VALUES, runner.OPEN_MINUTES_VALUES
    ):
        res_cur = runner._run_signals_and_backtest(df, symbol, mode, tm, om)
        with _patched_ib(causal_initial_balance):
            res_cau = runner._run_signals_and_backtest(df, symbol, mode, tm, om)
        rows.append({
            "symbol": symbol, "mode": mode, "target_mult": tm, "open_minutes": om,
            "premarket_leak_rows": premarket_leak_rows(df, om),
            "current": _bt_summary(res_cur),
            "causal": _bt_summary(res_cau),
        })
    return rows


def _bt_summary(res) -> dict:
    net = getattr(res, "net_pnl", None)
    if net is None:
        net = getattr(res, "total_pnl", None)
    return {
        "trades": int(res.total_trades),
        "pf": round(float(res.profit_factor), 3),
        "net_pnl": round(float(net), 2) if net is not None else None,
    }


# ---------------------------------------------------------------------------
# #752 -- VWAP
# ---------------------------------------------------------------------------


def audit_vwap() -> dict:
    from backtest import run_mes_vwap_rank1 as runner
    from backtest import vwap_backtester as vbt
    from backtest.vwap_signals import generate_vwap_signals

    data_file = runner._find_data_file(CACHE_DIR)
    df = runner._load_data(data_file)
    et_hour = df.index.tz_convert("America/New_York").hour
    rth = (et_hour >= RTH_OPEN_HOUR_ET) & (et_hour <= RTH_LAST_HOUR_ET)

    grid = list(itertools.product([1.5, 2.0, 2.5], [0.25, 0.5, 0.75], [True, False], [True, False]))
    combos = []
    for band, stop, rev, reg in grid:
        params = {"band_mult": band, "stop_mult": stop, "require_reversal_bar": rev, "regime_filter": reg}
        sig = generate_vwap_signals(df, symbol="MES", **params)
        is_entry = sig["vwap_signal"].isin(["LONG_ENTRY", "SHORT_ENTRY"]).to_numpy()
        n_entries = int(is_entry.sum())
        n_outside = int((is_entry & ~np.asarray(rth)).sum())
        cur = vbt.run_vwap_backtest(df, symbol="MES", **params).summary()
        cau = vbt.run_vwap_backtest(df[rth], symbol="MES", **params).summary()
        combos.append({
            **params,
            "entries": n_entries,
            "entries_outside_rth": n_outside,
            "pct_outside_rth": round(n_outside / n_entries, 4) if n_entries else None,
            "current": {k: cur.get(k) for k in ("total_trades", "profit_factor", "net_pnl")},
            "rth_only": {k: cau.get(k) for k in ("total_trades", "profit_factor", "net_pnl")},
        })
    return {"data_file": data_file.name, "bars": len(df), "rth_bars": int(rth.sum()), "combos": combos}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", type=Path, help="write full results to this path")
    ap.add_argument("--skip-ib", action="store_true")
    ap.add_argument("--skip-vwap", action="store_true")
    args = ap.parse_args()

    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not args.skip_ib:
        report["issue_751_ib"] = [row for s in IB_SYMBOLS for row in audit_ib(s)]
        for r in report["issue_751_ib"]:
            print(f"#751 {r['symbol']} {r['mode']:4s} tm={r['target_mult']} om={r['open_minutes']:2d} "
                  f"leak_rows={r['premarket_leak_rows']:6d} current={r['current']} causal={r['causal']}")
    if not args.skip_vwap:
        report["issue_752_vwap"] = audit_vwap()
        v = report["issue_752_vwap"]
        print(f"#752 data={v['data_file']} bars={v['bars']} rth_bars={v['rth_bars']}")
        for c in v["combos"]:
            print(f"#752 band={c['band_mult']} stop={c['stop_mult']} rev={c['require_reversal_bar']!s:5s} "
                  f"reg={c['regime_filter']!s:5s} entries={c['entries']:5d} outside_rth={c['entries_outside_rth']:5d} "
                  f"({c['pct_outside_rth']}) current={c['current']} rth_only={c['rth_only']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
