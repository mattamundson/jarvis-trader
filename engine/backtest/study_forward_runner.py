#!/usr/bin/env python
"""Locked-spec forward evaluation for a preregistered ThinkScript study mode.

This runner performs no parameter selection. It rejects parameter dictionaries
outside the study's declared grid and evaluates only rows strictly after the
supplied cutoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.backtester import Backtester  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.studies import load_study  # noqa: E402

CAPITAL = 50_000.0
COMMISSION_PER_CONTRACT = 1.42
SLIPPAGE_TICKS = 1.0
SPREAD_TICKS = 0.5


def load_forward_data(path: Path, cutoff: str) -> pd.DataFrame:
    """Load UTC OHLCV rows strictly after the locked WFO cutoff."""
    if not path.is_file():
        raise FileNotFoundError(f"forward data file does not exist: {path}")
    frame = pd.read_csv(path)
    frame.columns = [column.lower() for column in frame.columns]
    timestamp_column = "timestamp" if "timestamp" in frame.columns else "datetime"
    if timestamp_column not in frame.columns:
        raise ValueError("forward data requires timestamp or datetime column")
    frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True)
    frame = frame.set_index(timestamp_column).sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"forward data missing columns: {sorted(missing)}")
    cutoff_timestamp = pd.Timestamp(cutoff)
    cutoff_timestamp = (
        cutoff_timestamp.tz_localize("UTC")
        if cutoff_timestamp.tzinfo is None
        else cutoff_timestamp.tz_convert("UTC")
    )
    forward = frame[frame.index > cutoff_timestamp].copy()
    if forward.empty:
        raise ValueError(f"forward data contains no rows after cutoff {cutoff}")
    if not bool((forward.index > cutoff_timestamp).all()):
        raise AssertionError("pre-cutoff rows leaked into forward evaluation")
    return forward


def validate_locked_params(study: object, mode: str, params: dict[str, object]) -> None:
    """Require an exact member of the study's preregistered parameter grid."""
    modes = getattr(study, "MODES", None)
    grid_function = getattr(study, "grid", None)
    if not isinstance(modes, list) or mode not in modes or not callable(grid_function):
        raise ValueError(f"study does not declare mode {mode!r}")
    declared = grid_function(mode)
    if params not in declared:
        raise ValueError(
            f"locked params {params!r} are not in the preregistered grid for mode {mode!r}"
        )


def run_forward(
    *,
    study_name: str,
    mode: str,
    symbol: str,
    data_path: Path,
    cutoff: str,
    params: dict[str, object],
    output_path: Path,
) -> dict[str, object]:
    """Run and persist one locked forward evaluation."""
    study = load_study(study_name)
    validate_locked_params(study, mode, params)
    frame = load_forward_data(data_path, cutoff)
    signals = study.generate(frame, mode=mode, **params)
    spec = CONTRACT_SPECS[symbol]
    result = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        commission_per_contract=COMMISSION_PER_CONTRACT,
        slippage_ticks=SLIPPAGE_TICKS,
        spread_ticks=SPREAD_TICKS,
        eod_close=True,
        fixed_contracts=1,
    ).run(signals, symbol=symbol, multiplier=spec.multiplier)
    data_hash = file_sha256(data_path)
    locked_spec = {
        "cutoff_exclusive": cutoff,
        "data_sha256": data_hash,
        "execution_costs": {
            "commission_per_contract": COMMISSION_PER_CONTRACT,
            "slippage_ticks": SLIPPAGE_TICKS,
            "spread_ticks": SPREAD_TICKS,
        },
        "mode": mode,
        "params": params,
        "study": study_name,
        "symbol": symbol,
    }
    specification_hash = hashlib.sha256(
        json.dumps(locked_spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report: dict[str, object] = {
        "bar_count": len(frame),
        "cutoff_exclusive": cutoff,
        "data_file": data_path.name,
        "data_sha256": data_hash,
        "execution_costs": locked_spec["execution_costs"],
        "first_bar": frame.index.min().isoformat(),
        "last_bar": frame.index.max().isoformat(),
        "mode": mode,
        "params": params,
        "result": result.to_dict(),
        "study": study_name,
        "symbol": symbol,
        "specification_hash": specification_hash,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--data-file", required=True, type=Path)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--params", required=True, type=json.loads)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run_forward(
        study_name=args.study,
        mode=args.mode,
        symbol=args.symbol,
        data_path=args.data_file,
        cutoff=args.cutoff,
        params=args.params,
        output_path=args.output,
    )
    result = report["result"]
    if not isinstance(result, dict):
        raise TypeError("forward report result must be an object")
    print(
        f"{args.study}/{args.mode} {args.symbol}: bars={report['bar_count']} "
        f"trades={result['total_trades']} PF={result['profit_factor']:.4f} "
        f"return={result['total_return_pct']:.4%} DD={result['max_drawdown_pct']:.4%}"
    )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
