#!/usr/bin/env python3
"""jarvis_tearsheet.py — master QuantStats tearsheet generator.

Audit F-13 deliverable (2026-06-11), adapted from the April 2026 QuantStats
integration analysis. Reuses engine/reports/quantstats_metrics.py for the
metric suite instead of redefining it; adds qs.reports.html visual tearsheets
and a cumulative METRICS_SNAPSHOT.json.

Usage (run with the engine venv python from the repo root):
    engine\\.venv\\Scripts\\python.exe scripts\\jarvis_tearsheet.py --source paper
    engine\\.venv\\Scripts\\python.exe scripts\\jarvis_tearsheet.py --source backtest --file <result.json>
    engine\\.venv\\Scripts\\python.exe scripts\\jarvis_tearsheet.py --source rl --run <run_id>

Outputs:
    docs/reports/tearsheets/YYYY-MM-DD_HH-MM_<source>_<label>.html
    docs/reports/METRICS_SNAPSHOT.json   (cumulative, keyed source_label)

Exit codes: 0 = gates passed, 1 = gates failed or insufficient data, 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from reports.quantstats_metrics import compute_quantstats_metrics  # noqa: E402

ENGINE_BASE = os.environ.get("JARVIS_ENGINE_URL", "http://127.0.0.1:8010")
TEARSHEET_DIR = REPO_ROOT / "docs" / "reports" / "tearsheets"
SNAPSHOT_PATH = REPO_ROOT / "docs" / "reports" / "METRICS_SNAPSHOT.json"

# Production gates per the April 2026 analysis (10 gates).
# These gate the PAPER-VALIDATION / RL-EVAL layer; they complement gate v2
# (pf_ci_lower / p_edge / mc_dd / dsr), which authorizes strategies. Two layers.
PRODUCTION_GATES: dict[str, tuple[str, float]] = {
    "profit_factor": (">=", 2.0),
    "sortino": (">=", 1.5),
    "calmar": (">=", 1.0),
    "win_rate": (">=", 0.55),
    "max_dd": ("<=", 0.15),  # compared on abs()
    "tail_ratio": (">=", 1.0),
    "common_sense_ratio": (">=", 1.5),
    "ulcer_perf_index": (">=", 0.7),
    "gain_to_pain": (">=", 0.7),
    "exposure": (">=", 0.20),
}


def _api_key() -> str:
    env_path = ENGINE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("API_KEY", "")


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"{ENGINE_BASE}{path}",
        params=params or {},
        headers={"X-API-Key": _api_key()},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_paper_returns(lookback_days: int = 90) -> pd.Series:
    """Daily returns via the engine's own QS endpoint source data is not exposed,
    so rebuild from /reports/quantstats inputs: prefer pnl_snapshots semantics by
    pulling daily monthly buckets is lossy — instead hit decisions/trades.

    Pragmatic source: GET /reports/quantstats gives metrics but not the series;
    the series itself comes from the engine DB. We reuse the engine's own
    loader by querying the DB directly when run on the same machine.
    """
    db_path = Path(os.environ.get("DB_PATH", "")) if os.environ.get("DB_PATH") else ENGINE_DIR / "data" / "jarvis_trader.db"
    if db_path.exists():
        from reports.quantstats_metrics import _load_pnl_series

        returns, source, n_trades, start, end = _load_pnl_series(
            str(db_path), run_id=None, days=lookback_days
        )
        returns.name = "JARVIS_paper"
        return returns
    return pd.Series(dtype=float)


def fetch_backtest_returns(file_path: str) -> pd.Series:
    path = Path(file_path)
    if not path.exists():
        print(f"[tearsheet] File not found: {file_path}")
        return pd.Series(dtype=float)
    result = json.loads(path.read_text(encoding="utf-8"))
    if "returns" in result and result["returns"]:
        series = pd.Series(result["returns"])
        series.index = pd.to_datetime(series.index)
        return series.sort_index().rename(path.stem)
    trades = result.get("trades", [])
    if trades:
        daily: dict = {}
        for t in trades:
            date = pd.to_datetime(t["exit_time"]).normalize()
            daily[date] = daily.get(date, 0.0) + t["pnl_pct"] / 100.0
        return pd.Series(daily).sort_index().rename(path.stem)
    return pd.Series(dtype=float)


def fetch_rl_returns(run_name: str) -> pd.Series:
    resp = requests.post(
        f"{ENGINE_BASE}/strategies/rl/evaluate",
        json={"run_name": run_name},
        headers={"X-API-Key": _api_key()},
        timeout=180,
    )
    resp.raise_for_status()
    trades = resp.json().get("trades", [])
    if not trades:
        return pd.Series(dtype=float)
    return (
        pd.Series(
            {pd.to_datetime(t["exit_time"]): t["pnl_pct"] / 100.0 for t in trades}
        )
        .sort_index()
        .rename(f"JARVIS_RL_{run_name}")
    )


def get_benchmark(ticker: str, returns: pd.Series) -> pd.Series | None:
    try:
        import yfinance as yf

        df = yf.download(
            ticker,
            start=str(returns.index.min().date()),
            end=str(returns.index.max().date()),
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        bm = close.pct_change().dropna()
        bm.index = pd.to_datetime(bm.index)
        return bm.reindex(returns.index, fill_value=0.0).rename(ticker)
    except Exception as exc:  # benchmark is optional — never fail the tearsheet
        print(f"[tearsheet] benchmark {ticker} unavailable: {exc}")
        return None


def evaluate_gates(metrics: dict) -> tuple[bool, list[str]]:
    failures = []
    for gate, (op, threshold) in PRODUCTION_GATES.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"{gate}: MISSING")
            continue
        if gate == "max_dd":
            val = abs(val)
        ok = (op == ">=" and val >= threshold) or (op == "<=" and val <= threshold)
        if not ok:
            failures.append(f"{gate}: {val:.4f} (need {op} {threshold})")
    return not failures, failures


def update_snapshot(source: str, label: str, metrics: dict, passed: bool, failures: list[str]):
    snapshot = {}
    if SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snapshot = {}
    snapshot[f"{source}_{label}"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "label": label,
        "gate_passed": passed,
        "failures": failures,
        "metrics": {
            k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in metrics.items()
            if k not in ("monthly_returns", "rolling_sharpe_30d")
        },
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS QuantStats tearsheet generator")
    parser.add_argument("--source", choices=["paper", "backtest", "rl"], required=True)
    parser.add_argument("--file", help="Backtest JSON path (source=backtest)")
    parser.add_argument("--run", help="RL run id (source=rl)")
    parser.add_argument("--benchmark", help="Benchmark ticker (default SPY, ES=F for rl)")
    parser.add_argument("--lookback", type=int, default=90)
    args = parser.parse_args()

    if args.source == "paper":
        returns, label, bm_ticker = fetch_paper_returns(args.lookback), "paper", "SPY"
    elif args.source == "backtest":
        if not args.file:
            print("--file required for backtest source")
            return 2
        returns, label, bm_ticker = fetch_backtest_returns(args.file), Path(args.file).stem, "SPY"
    else:
        if not args.run:
            print("--run required for rl source")
            return 2
        returns, label, bm_ticker = fetch_rl_returns(args.run), args.run, "ES=F"
    bm_ticker = args.benchmark or bm_ticker

    if returns.empty or len(returns) < 5:
        print(f"[tearsheet] insufficient data for {args.source}/{label} (n={len(returns)})")
        return 1

    metrics = compute_quantstats_metrics(returns, source=args.source)
    metrics["n_trades"] = len(returns)
    metrics["start_date"] = returns.index.min().strftime("%Y-%m-%d")
    metrics["end_date"] = returns.index.max().strftime("%Y-%m-%d")
    passed, failures = evaluate_gates(metrics)

    print(f"\n=== JARVIS tearsheet: {args.source}/{label} (n={len(returns)}) ===")
    for k in PRODUCTION_GATES:
        v = metrics.get(k)
        mark = "?" if v is None else ("PASS" if f"{k}:" not in " ".join(failures) else "FAIL")
        print(f"  {k:<22} {v if v is None else round(v, 4)!s:>12}  {mark}")
    print(f"  => {'ALL GATES PASSED' if passed else f'{len(failures)} GATE FAILURES'}")

    # Visual tearsheet
    TEARSHEET_DIR.mkdir(parents=True, exist_ok=True)
    out = TEARSHEET_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{args.source}_{label}.html"
    try:
        import quantstats as qs

        qs.reports.html(
            returns,
            benchmark=get_benchmark(bm_ticker, returns),
            title=f"JARVIS {args.source.upper()} — {label}",
            output=str(out),
            download_filename=str(out),
        )
        print(f"tearsheet: {out}")
    except Exception as exc:
        print(f"[tearsheet] HTML generation failed (metrics still recorded): {exc}")

    update_snapshot(args.source, label, metrics, passed, failures)
    print(f"snapshot:  {SNAPSHOT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
