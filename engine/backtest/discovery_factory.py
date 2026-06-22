#!/usr/bin/env python
"""
JARVIS TRADER -- discovery factory (Phase 3, slice 1).

Replaces the 55 hand-coded one-off `run_*.py` runners (each a copy-paste of the
same WFO + gate-v2 + verdict machinery) with a single config-driven sweep: a
registry of (symbol x family x interval x param-grid) strategy specs, each run
through the canonical reusable pipeline in `backtest.wfo_lifecycle`
(`run_wfo` -> `run_fixed_params_sweep` -> `run_cost_sweep` -> `compute_gate_v2`),
then ranked into a leaderboard.

Why this slice exists: deep 1h history is NOT freely available (IB caps micro 1h
at ~26mo -- see project_cache_coverage_manifest_2026_06_22), so the path to the
30-OOS-trade gate floor is HIGHER-FREQUENCY families (15m/5m) within the history
we have, not deeper 1h. Empirically confirmed: MES 15m trend produces 32-85
trades/combo vs 1h's 17. This factory sweeps families x intervals to find combos
with BOTH adequate trades AND real edge.

Safety: research only. Reuses the canonical gate machinery (never reimplements
it); writes verdict JSONs to data/discovery_factory/ -- deliberately NOT
gate_v2_verdicts/ (the store the live engine reads for tradeability), so a
discovery candidate can NEVER silently authorize live/paper trading. Promotion
is a human decision (Phase 1 unified config). Pure offline backtest over cached
bars: no signals.py/config/.env writes, no engine restart, no live endpoint.

Usage (from engine/):
    .venv/Scripts/python -m backtest.discovery_factory --dry-run        # plan only
    .venv/Scripts/python -m backtest.discovery_factory                  # run all specs
    .venv/Scripts/python -m backtest.discovery_factory --symbol MES --interval 15m
    .venv/Scripts/python -m backtest.discovery_factory --cache-dir <path>
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# The Backtester constructs config.TradingConfig(), which fails fast if API_KEY
# is unset. A git worktree has no .env (gitignored), so supply a harmless offline
# placeholder ONLY when nothing real is set. This is pure offline backtesting --
# the factory never starts the API server or makes an authenticated call; when
# run from the main engine dir, its real .env value wins (setdefault is a no-op).
os.environ.setdefault("API_KEY", "offline-discovery-factory")

# Reuse the canonical WFO + gate-v2 pipeline -- do NOT reimplement.
from backtest._gate_v2_helpers import MIN_OOS_TRADES_TOTAL, _find_latest_cache  # noqa: E402
from backtest.atr_channel_signals import generate_atr_channel_signals  # noqa: E402
from backtest.breakout_signals import generate_donchian_breakout_signals  # noqa: E402
from backtest.donchian_signals import generate_donchian_signals  # noqa: E402
from backtest.meanrev_signals import generate_bollinger_rsi_signals  # noqa: E402
from backtest.rsi_breakout_signals import generate_rsi_breakout_signals  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402
from backtest.wfo_lifecycle import (  # noqa: E402
    WFOConfig,
    compute_gate_v2,
    generate_windows,
    run_cost_sweep,
    run_fixed_params_sweep,
    run_wfo,
)

# Per-contract dollar multipliers. Backtester handles tick size internally by
# symbol; we only supply the point multiplier (mirrors run_mes_trend_15m_rank1).
CONTRACT_SPECS = {"MES": 5.0, "MGC": 10.0, "MNQ": 2.0}
SUPPORTED_SYMBOLS = frozenset(CONTRACT_SPECS)

CAPITAL = 50_000.0  # ALT gate path requires $50K+ accounts
OUTPUT_DIR = engine_root / "data" / "discovery_factory"

# Standard 4-tier cost sweep (identical across all runners).
COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}
_DEFAULT_COMMISSION = 0.62
_DEFAULT_SLIPPAGE_TICKS = 2.0


def grid(**axes: list) -> list[dict]:
    """Cartesian product of named axes -> list of param dicts.

    grid(fast=[8, 12], slow=[24, 36]) ->
        [{fast:8,slow:24},{fast:8,slow:36},{fast:12,slow:24},{fast:12,slow:36}]
    """
    keys = list(axes)
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*axes.values())]


@dataclass(frozen=True)
class StrategySpec:
    """One (symbol, family, interval) sweep definition."""

    symbol: str
    family: str
    interval: str
    signal_fn: Callable
    param_grid: list[dict]
    train_months: int
    test_months: int = 1
    step_months: int = 1
    # Higher-frequency bars => more entries; raise the per-window floor so an
    # IS window isn't won by a 1-trade fluke (mirrors run_mes_trend_15m_rank1).
    min_oos_trades_per_window: int = 1
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"{self.symbol}_{self.family}_{self.interval}"

    @property
    def n_combos(self) -> int:
        return len(self.param_grid)


# ---------------------------------------------------------------------------
# Initial registry (slice 1) -- deliberately small. Tests the central thesis:
# does dropping to 15m break the 30-trade floor that starves 1h trend, and do
# any combos clear gate-v2 on the adequate sample? MGC 1h trend is the known
# PASS sanity anchor. Grids mirror the validated one-off runners.
# ---------------------------------------------------------------------------
def default_registry() -> list[StrategySpec]:
    return [
        # MGC 1h SMA trend -- known gate-v2 PASS; sanity anchor for the harness.
        StrategySpec(
            symbol="MGC",
            family="sma_trend",
            interval="1h",
            signal_fn=generate_sma_trend_signals,
            param_grid=grid(fast=[40, 50, 60], slow=[100, 120, 200], atr_trail_mult=[1.5, 2.0]),
            train_months=6,
            test_months=2,
            step_months=1,
            tags=("anchor", "known_pass"),
        ),
        # MES 1h SMA trend -- known INSUFFICIENT_SAMPLE (17 OOS < 30); baseline.
        StrategySpec(
            symbol="MES",
            family="sma_trend",
            interval="1h",
            signal_fn=generate_sma_trend_signals,
            param_grid=grid(fast=[40, 50, 60], slow=[120, 200], atr_trail_mult=[2.0]),
            train_months=6,
            test_months=1,
            step_months=1,
            tags=("baseline", "starved_1h"),
        ),
        # MES 15m SMA trend -- the pivot: more trades on the same history.
        StrategySpec(
            symbol="MES",
            family="sma_trend",
            interval="15m",
            signal_fn=generate_sma_trend_signals,
            param_grid=grid(fast=[8, 12, 16], slow=[24, 36, 48], atr_trail_mult=[1.5, 2.0, 2.5]),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "higher_freq"),
        ),
        # MES 1h Donchian breakout -- a different family on the flagship symbol.
        StrategySpec(
            symbol="MES",
            family="donchian",
            interval="1h",
            signal_fn=generate_donchian_signals,
            param_grid=grid(
                lookback_entry=[20, 40, 55], lookback_exit=[10, 20], atr_trail_mult=[2.0]
            ),
            train_months=6,
            test_months=1,
            step_months=1,
            tags=("diversify",),
        ),
        # MES 15m Donchian breakout -- higher-freq breakout candidate.
        StrategySpec(
            symbol="MES",
            family="donchian",
            interval="15m",
            signal_fn=generate_donchian_signals,
            param_grid=grid(
                lookback_entry=[20, 40], lookback_exit=[10, 20], atr_trail_mult=[2.0, 2.5]
            ),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "higher_freq", "diversify"),
        ),
        # --- Expanded edge hunt (round 2): more families on the freed-up sample ---
        # MES 15m Bollinger+RSI mean-reversion -- a non-trend family on the pivot TF.
        StrategySpec(
            symbol="MES",
            family="bollinger_rsi",
            interval="15m",
            signal_fn=generate_bollinger_rsi_signals,
            param_grid=grid(
                bb_period=[20],
                bb_std=[2.0, 2.5],
                rsi_long=[25, 30],
                rsi_short=[70, 75],
                stop_atr_mult=[1.5],
            ),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "meanrev"),
        ),
        # MES 15m ATR-channel breakout.
        StrategySpec(
            symbol="MES",
            family="atr_channel",
            interval="15m",
            signal_fn=generate_atr_channel_signals,
            param_grid=grid(ema_period=[20, 30], atr_mult=[1.5, 2.0, 2.5], atr_stop_mult=[2.0]),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "breakout"),
        ),
        # MES 15m RSI breakout.
        StrategySpec(
            symbol="MES",
            family="rsi_breakout",
            interval="15m",
            signal_fn=generate_rsi_breakout_signals,
            param_grid=grid(
                rsi_oversold=[20, 25],
                rsi_overbought=[75, 80],
                entry_period=[20, 40],
                atr_stop_mult=[2.0],
            ),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "meanrev"),
        ),
        # MES 15m volume-confirmed Donchian breakout (distinct from plain donchian).
        StrategySpec(
            symbol="MES",
            family="donchian_breakout",
            interval="15m",
            signal_fn=generate_donchian_breakout_signals,
            param_grid=grid(donchian_period=[20, 40], vol_mult=[0.0, 1.0], stop_atr_mult=[2.0]),
            train_months=3,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=3,
            tags=("pivot", "breakout"),
        ),
        # MES 1h ATR-channel -- diversify the flagship's 1h families.
        StrategySpec(
            symbol="MES",
            family="atr_channel",
            interval="1h",
            signal_fn=generate_atr_channel_signals,
            param_grid=grid(ema_period=[20, 50], atr_mult=[2.0, 2.5], atr_stop_mult=[2.0]),
            train_months=6,
            test_months=1,
            step_months=1,
            tags=("diversify",),
        ),
        # MGC 1h ATR-channel -- more families on the strongest symbol.
        StrategySpec(
            symbol="MGC",
            family="atr_channel",
            interval="1h",
            signal_fn=generate_atr_channel_signals,
            param_grid=grid(ema_period=[20, 50], atr_mult=[2.0, 2.5], atr_stop_mult=[2.0]),
            train_months=6,
            test_months=2,
            step_months=1,
            tags=("diversify",),
        ),
        # MGC 1h volume-confirmed Donchian breakout.
        StrategySpec(
            symbol="MGC",
            family="donchian_breakout",
            interval="1h",
            signal_fn=generate_donchian_breakout_signals,
            param_grid=grid(donchian_period=[20, 40, 55], vol_mult=[0.0, 1.0], stop_atr_mult=[2.0]),
            train_months=6,
            test_months=2,
            step_months=1,
            tags=("diversify",),
        ),
        # MGC 1h Bollinger+RSI mean-reversion.
        StrategySpec(
            symbol="MGC",
            family="bollinger_rsi",
            interval="1h",
            signal_fn=generate_bollinger_rsi_signals,
            param_grid=grid(
                bb_period=[20],
                bb_std=[2.0, 2.5],
                rsi_long=[25, 30],
                rsi_short=[70, 75],
                stop_atr_mult=[1.5],
            ),
            train_months=6,
            test_months=2,
            step_months=1,
            tags=("meanrev",),
        ),
    ]


# ---------------------------------------------------------------------------
# Data loading (interval-agnostic; mirrors run_mes_trend_15m_rank1._load_data)
# ---------------------------------------------------------------------------
def load_interval_bars(symbol: str, interval: str, cache_dir: Path) -> pd.DataFrame:
    """Load the freshest cached bars for (symbol, interval) -- any interval."""
    data_file = _find_latest_cache(Path(cache_dir), symbol, suffix=f"_{interval}.csv")
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    df.attrs["source_file"] = data_file.name
    return df


def _make_run_fn(spec: StrategySpec) -> Callable:
    """Build the (df, params) -> BacktestResult closure wfo_lifecycle expects.

    params may carry 'commission'/'slippage_ticks' (cost-sweep) plus the signal
    kwargs; we route each to the right consumer.
    """
    from backtest.backtester import Backtester

    multiplier = CONTRACT_SPECS[spec.symbol]

    def run_fn(df: pd.DataFrame, params: dict):
        sig_params = {k: v for k, v in params.items() if k not in ("commission", "slippage_ticks")}
        sig = spec.signal_fn(df, **sig_params)
        bt = Backtester(
            initial_capital=CAPITAL,
            risk_per_trade=0.01,
            max_daily_loss=0.02,
            max_drawdown=0.05,
            t1_exit_pct=0.50,
            t2_exit_pct=0.30,
            commission_per_contract=params.get("commission", _DEFAULT_COMMISSION),
            slippage_ticks=params.get("slippage_ticks", _DEFAULT_SLIPPAGE_TICKS),
        )
        return bt.run(sig, symbol=spec.symbol, multiplier=multiplier)

    return run_fn


def _wfo_config(spec: StrategySpec) -> WFOConfig:
    return WFOConfig(
        train_len=pd.DateOffset(months=spec.train_months),
        test_len=pd.DateOffset(months=spec.test_months),
        step_len=pd.DateOffset(months=spec.step_months),
        min_bars=30,
    )


def _champion_params(window_records: list[dict], fallback: dict) -> dict:
    """Most-frequently IS-selected param set across windows (cost-sweep target)."""
    if not window_records:
        return fallback
    votes = Counter(tuple(sorted(r["best_params"].items())) for r in window_records)
    best = votes.most_common(1)[0][0]
    return dict(best)


def plan_spec(spec: StrategySpec, cache_dir: Path) -> dict:
    """Dry-run plan for one spec: load bars, count WFO windows + total runs."""
    info: dict = {
        "symbol": spec.symbol,
        "family": spec.family,
        "interval": spec.interval,
        "label": spec.label,
        "n_combos": spec.n_combos,
        "tags": list(spec.tags),
    }
    if spec.symbol not in SUPPORTED_SYMBOLS:
        info["status"] = "UNSUPPORTED_SYMBOL"
        return info
    try:
        df = load_interval_bars(spec.symbol, spec.interval, cache_dir)
    except FileNotFoundError as exc:
        info["status"] = "NO_CACHE"
        info["error"] = str(exc)
        return info
    windows = generate_windows(df, _wfo_config(spec))
    info.update(
        status="READY",
        n_bars=len(df),
        start=str(df.index.min().date()),
        end=str(df.index.max().date()),
        source_file=df.attrs.get("source_file"),
        n_windows=len(windows),
        # IS grid search dominates: n_combos per window, plus a full-data
        # fixed-params sweep (n_combos) and a 4-tier cost sweep.
        approx_backtests=len(windows) * spec.n_combos + spec.n_combos + len(COST_SWEEP_TIERS),
    )
    return info


def run_spec(spec: StrategySpec, cache_dir: Path) -> dict:
    """Execute one spec's full WFO + gate-v2 evaluation; returns the verdict dict."""
    df = load_interval_bars(spec.symbol, spec.interval, cache_dir)
    run_fn = _make_run_fn(spec)
    cfg = _wfo_config(spec)
    min_trades = spec.min_oos_trades_per_window

    oos_results, window_records = run_wfo(df, spec.param_grid, run_fn, cfg, min_trades=min_trades)
    if not oos_results:
        return {
            "label": spec.label,
            "symbol": spec.symbol,
            "family": spec.family,
            "interval": spec.interval,
            "verdict": "NO_WINDOWS",
            "reason": "no OOS windows formed (insufficient data or all IS failed)",
            "source_file": df.attrs.get("source_file"),
        }

    fixed = run_fixed_params_sweep(df, spec.param_grid, run_fn, min_trades=min_trades)
    champion = _champion_params(window_records, spec.param_grid[0])
    cost = run_cost_sweep(df, champion, COST_SWEEP_TIERS, run_fn, min_trades=min_trades)
    gate = compute_gate_v2(oos_results, spec.n_combos, fixed, cost, min_trades=min_trades)

    # Sample-adequacy override. compute_gate_v2 grades edge metrics (PF-CI, p_edge,
    # DSR, MC-DD, consistency) but does NOT gate on the TOTAL OOS trade count, so a
    # handful of trades concentrated in a single window can spuriously score PASS
    # (observed live: MES_rsi_breakout_15m, 5 trades in 1 of 6 windows -> PASS).
    # Mirror the production runners (run_cl_trend_rank1.py:370): a verdict on fewer
    # than MIN_OOS_TRADES_TOTAL trades is statistically meaningless, so override to
    # INSUFFICIENT_SAMPLE -- a non-PASS verdict that can never authorize trading.
    total_oos = gate.get("total_oos_trades", 0)
    gate["sample_adequate"] = total_oos >= MIN_OOS_TRADES_TOTAL
    gate["min_oos_trades_total"] = MIN_OOS_TRADES_TOTAL
    if not gate["sample_adequate"]:
        gate["verdict"] = "INSUFFICIENT_SAMPLE"
        gate["passed_via"] = None
        gate["reasons"] = [
            f"INSUFFICIENT_SAMPLE: total_oos_trades={total_oos} < {MIN_OOS_TRADES_TOTAL} floor",
            *gate.get("reasons", []),
        ]

    verdict = {
        "label": spec.label,
        "symbol": spec.symbol,
        "family": spec.family,
        "interval": spec.interval,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_file": df.attrs.get("source_file"),
        "champion_params": champion,
        "wfo_config": {
            "train_months": spec.train_months,
            "test_months": spec.test_months,
            "step_months": spec.step_months,
            "min_oos_trades_per_window": min_trades,
            "n_combos": spec.n_combos,
        },
        "gate_v2": gate,
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "cost_survives_through": gate["cost_survives_through"],
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "sample_adequate": gate["sample_adequate"],
            "min_oos_trades_total": gate["min_oos_trades_total"],
        },
        "windows": window_records,
        "tags": list(spec.tags),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{spec.label}.json").write_text(json.dumps(verdict, indent=2, default=str))
    return verdict


def _select(registry: list[StrategySpec], symbol, family, interval) -> list[StrategySpec]:
    return [
        s
        for s in registry
        if (symbol is None or s.symbol == symbol)
        and (family is None or s.family == family)
        and (interval is None or s.interval == interval)
    ]


def _format_plan(plans: list[dict]) -> str:
    h = (
        f"{'SYMBOL':<7}{'FAMILY':<11}{'INT':<5}{'STATUS':<10}"
        f"{'BARS':>8}{'WINS':>6}{'COMBOS':>7}{'~RUNS':>8}  RANGE"
    )
    lines = [h, "-" * len(h)]
    total_runs = 0
    for p in plans:
        runs = p.get("approx_backtests", 0)
        total_runs += runs
        rng = f"{p.get('start', '-')}->{p.get('end', '-')}" if p.get("start") else "-"
        lines.append(
            f"{p['symbol']:<7}{p['family']:<11}{p['interval']:<5}{p['status']:<10}"
            f"{p.get('n_bars', '-'):>8}{p.get('n_windows', '-'):>6}{p['n_combos']:>7}"
            f"{runs if runs else '-':>8}  {rng}"
        )
    lines.append("")
    lines.append(f"{len(plans)} specs | ~{total_runs} total backtests planned")
    return "\n".join(lines)


def _rank_verdicts(verdicts: list[dict]) -> list[dict]:
    """Rank: PASS first, then by dsr desc, then pf_ci_lower desc."""
    order = {"PASS": 0, "FAIL": 1, "NO_WINDOWS": 2, "ERROR": 3}

    def key(v: dict):
        m = v.get("gate_v2_metrics", {}) or {}
        return (
            order.get(v.get("verdict", "FAIL"), 4),
            -(m.get("dsr") if m.get("dsr") is not None else -99),
            -(m.get("pf_ci_lower") if m.get("pf_ci_lower") is not None else -99),
        )

    return sorted(verdicts, key=key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS discovery factory (Phase 3 slice 1)")
    parser.add_argument("--dry-run", action="store_true", help="plan only; no backtests")
    parser.add_argument("--symbol", help="filter to one symbol")
    parser.add_argument("--family", help="filter to one family")
    parser.add_argument("--interval", help="filter to one interval")
    parser.add_argument(
        "--cache-dir", default=str(engine_root / "backtest" / "cache"), help="bar cache dir"
    )
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir)
    specs = _select(default_registry(), args.symbol, args.family, args.interval)
    if not specs:
        print("No specs match the given filters.")
        return 1

    if args.dry_run:
        plans = [plan_spec(s, cache_dir) for s in specs]
        print(_format_plan(plans))
        return 0 if all(p["status"] == "READY" for p in plans) else 2

    print(f"Running {len(specs)} discovery specs against {cache_dir}\n")
    verdicts = []
    for i, spec in enumerate(specs, 1):
        print(f"\n{'#' * 70}\n# [{i}/{len(specs)}] {spec.label}\n{'#' * 70}")
        try:
            v = run_spec(spec, cache_dir)
        except Exception as exc:  # noqa: BLE001 -- one bad spec must not kill the sweep
            print(f"  [SPEC ERROR] {spec.label}: {exc}")
            v = {
                "label": spec.label,
                "symbol": spec.symbol,
                "family": spec.family,
                "interval": spec.interval,
                "verdict": "ERROR",
                "error": str(exc),
            }
        verdicts.append(v)
        print(
            f"  -> {v.get('verdict')} "
            f"(dsr={v.get('gate_v2_metrics', {}).get('dsr', '-')}, "
            f"oos_trades={v.get('gate_v2_metrics', {}).get('total_oos_trades', '-')})"
        )

    print(f"\n{'=' * 70}\nLEADERBOARD\n{'=' * 70}")
    ranked = _rank_verdicts(verdicts)
    for v in ranked:
        m = v.get("gate_v2_metrics", {}) or {}
        print(
            f"  {v.get('verdict', '?'):<12} {v.get('symbol', '?'):<5} "
            f"{v.get('family', '?'):<10} {v.get('interval', '?'):<4} "
            f"pf_ci={m.get('pf_ci_lower', '-')} dsr={m.get('dsr', '-')} "
            f"oos_trades={m.get('total_oos_trades', '-')}"
        )
    n_pass = sum(1 for v in verdicts if v.get("verdict") == "PASS")
    print(f"\n{n_pass}/{len(verdicts)} specs PASS gate-v2.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    leaderboard = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "n_specs": len(verdicts),
        "n_pass": n_pass,
        "ranked": [
            {
                "label": v.get("label"),
                "verdict": v.get("verdict"),
                "passed_via": v.get("passed_via"),
                **{
                    k: (v.get("gate_v2_metrics", {}) or {}).get(k)
                    for k in ("pf_ci_lower", "dsr", "total_oos_trades")
                },
            }
            for v in ranked
        ],
    }
    (OUTPUT_DIR / "LEADERBOARD.json").write_text(json.dumps(leaderboard, indent=2, default=str))
    print(f"\nLeaderboard -> {OUTPUT_DIR / 'LEADERBOARD.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
