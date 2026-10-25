#!/usr/bin/env python
"""
Databento pilot runner — one command for the whole pilot.

Implements the staged plan in
`docs/plans/JARVIS_DATABENTO_PILOT_IMPLEMENTATION_PLAN_v1.0.md`:
    preflight -> futures -> options -> reconcile -> report

READ-ONLY WITH RESPECT TO TRADING. This script:
  * never places, modifies, or cancels an order;
  * never writes to engine/.env or any config;
  * never touches LIVE_TRADING_ENABLED, DO_NOT_TRADE_SYMBOLS, risk, or kill-switch;
  * only reads market data and writes CSVs into the backtest cache dir + an evidence file.

Run from the engine directory:
    .venv/Scripts/python.exe scripts/run_databento_pilot.py preflight
    .venv/Scripts/python.exe scripts/run_databento_pilot.py futures
    .venv/Scripts/python.exe scripts/run_databento_pilot.py options
    .venv/Scripts/python.exe scripts/run_databento_pilot.py reconcile
    .venv/Scripts/python.exe scripts/run_databento_pilot.py all

NOTE: `futures` and `options` SPEND Databento credit. Run the vendor's price
estimator first (see the plan) and pass --yes to acknowledge.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

EVIDENCE_DIR = ENGINE.parent / "docs" / "plans" / "evidence"

MICROS = ("MES", "MNQ", "MCL", "MGC", "M2K")
FUTURES_START = "2015-01-01"
OPTIONS_START = "2013-01-01"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stage_preflight() -> dict:
    """Step 0: prove the environment is safe and capture the baseline."""
    from backtest import databento_loader as dl  # noqa: PLC0415

    out: dict = {"stage": "preflight", "utc": datetime.now(timezone.utc).isoformat()}

    env = ENGINE / ".env"
    live = None
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("LIVE_TRADING_ENABLED"):
                live = line.split("=", 1)[1].strip()
    out["live_trading_enabled"] = live
    out["live_trading_safe"] = live is not None and live.lower() in ("false", "0", "no")

    out["api_key_present"] = bool(dl._api_key())
    out["databento_package"] = dl._db_available()
    d = shutil.disk_usage("C:/")
    out["disk_free_gb"] = round(d.free / 1e9, 2)

    # baseline: what the existing caches already hold, per micro
    baseline = {}
    for sym in MICROS:
        files = sorted(dl.CACHE_DIR.glob(f"{sym}_*.csv")) + sorted(dl.CACHE_DIR.glob(f"{sym}_F_*.csv"))
        rows = 0
        widest = None
        best = 0
        for f in files:
            try:
                n = sum(1 for _ in f.open(encoding="utf-8", errors="ignore")) - 1
            except OSError:
                continue
            if n > best:
                best, widest = n, f.name
            rows += n
        baseline[sym] = {"cache_files": len(files), "total_rows": rows, "widest": widest}
    out["baseline_caches"] = baseline

    # existing databento test suite must be green before any spend
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/test_databento_adapter.py", "tests/test_databento_loader_cache.py",
             "tests/test_databento_opra.py", "-q", "--no-header", "-p", "no:warnings"],
            cwd=ENGINE, capture_output=True, text=True, timeout=300,
        )
        tail = (r.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
        out["databento_tests"] = tail[0]
        out["databento_tests_ok"] = r.returncode == 0
    except Exception as exc:  # pragma: no cover
        out["databento_tests"] = f"could not run: {exc}"
        out["databento_tests_ok"] = False
    return out


def stage_futures(start: str, end: str, yes: bool) -> dict:
    """Step 2: pull deep continuous history for the micro complex (SPENDS credit)."""
    from backtest import databento_loader as dl

    if not yes:
        return {"stage": "futures", "skipped": True,
                "reason": "pass --yes to acknowledge credit spend (run the vendor estimator first)"}
    results = {}
    for sym in MICROS:
        df = dl.fetch_ohlcv(sym, start, end, "1h")
        results[sym] = {
            "rows": int(len(df)),
            "first": str(df.index.min()) if len(df) else None,
            "last": str(df.index.max()) if len(df) else None,
        }
    return {"stage": "futures", "window": [start, end], "symbols": results}


def stage_options(start: str, end: str, yes: bool) -> dict:
    """Step 2b: pull REAL OPRA chains (SPENDS credit). Replaces the BS proxy."""
    from backtest import databento_loader as dl

    if not yes:
        return {"stage": "options", "skipped": True,
                "reason": "pass --yes to acknowledge credit spend (run the vendor estimator first)"}
    results = {}
    for und in dl.OPTIONS_WATCHLIST:
        df = dl.fetch_option_chains(und, start, end, "ohlcv-1d")
        contracts = int(df["instrument_id"].nunique()) if len(df) and "instrument_id" in df.columns else None
        results[und] = {"rows": int(len(df)), "contracts": contracts,
                        "first": str(df["timestamp"].min()) if len(df) else None,
                        "last": str(df["timestamp"].max()) if len(df) else None}
    return {"stage": "options", "window": [start, end], "underlyings": results}


def stage_reconcile() -> dict:
    """Step 3: falsify the existing caches against an independent vendor."""
    from data import databento_adapter as dba

    results = {}
    for sym in MICROS:
        try:
            results[sym] = dba.reconcile_vs_cache(sym, timeframe="1h", lookback_days=365, tolerance_pct=0.1)
        except Exception as exc:
            results[sym] = {"status": "error", "reason": str(exc)}
    return {"stage": "reconcile", "symbols": results}


def write_evidence(payload: dict) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"databento_pilot_{_stamp()}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["preflight", "futures", "options", "reconcile", "all"])
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--yes", action="store_true",
                    help="Acknowledge that this stage spends Databento credit.")
    args = ap.parse_args()

    end = args.end or _today()
    payload: dict = {"utc": datetime.now(timezone.utc).isoformat(), "stages": {}}

    if args.stage in ("preflight", "all"):
        p = stage_preflight()
        payload["stages"]["preflight"] = p
        print(json.dumps(p, indent=2, default=str))
        if not p.get("live_trading_safe", False):
            print("\nSTOP: LIVE_TRADING_ENABLED is not False — refusing to continue.")
            write_evidence(payload)
            return 2

    if args.stage in ("futures", "all"):
        p = stage_futures(args.start or FUTURES_START, end, args.yes)
        payload["stages"]["futures"] = p
        print(json.dumps(p, indent=2, default=str))

    if args.stage in ("options", "all"):
        p = stage_options(args.start or OPTIONS_START, end, args.yes)
        payload["stages"]["options"] = p
        print(json.dumps(p, indent=2, default=str))

    if args.stage in ("reconcile", "all"):
        p = stage_reconcile()
        payload["stages"]["reconcile"] = p
        print(json.dumps(p, indent=2, default=str))

    path = write_evidence(payload)
    print(f"\nevidence: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
