#!/usr/bin/env python
"""
JARVIS batch iteration harness — grid × VIX-condition × Monte Carlo on deep data.

WHY: the existing run_*_rankN.py runners are hand-wired per strategy/rank and
each carries its own WFO loop. This harness turns parameter grids × VIX
filters/regimes × MC stress into one repeatable screening sweep with a results
table — so "more backtests, more iterations" is a config change, not a new runner.

USAGE (from engine/):
    # Smoke: one combo, truncated tail, fast (proves the real wiring works):
    .venv/Scripts/python backtest/iterate.py --symbol MES --smoke
    # Full deep sweep, default MES grid, plain SMA trend:
    .venv/Scripts/python backtest/iterate.py --symbol MES \
        --out backtest/results/iterate_mes_2026-08-17.json
    # VIX-conditional sweep (absolute range): only enter when 13 <= VIX <= 30:
    .venv/Scripts/python backtest/iterate.py --symbol MES --vix-min 13 --vix-max 30 \
        --vix-csv data/vix_daily.csv --out backtest/results/iterate_mes_vix_2026-08-17.json
    # VIX percentile-regime blocking: separate row per blocked tier set:
    .venv/Scripts/python backtest/iterate.py --symbol MES \
        --vix-regimes Crisis,HighVol --vix-csv data/vix_daily.csv --out ...
    # Custom grid + fixed_contracts (equal-weight basis):
    .venv/Scripts/python backtest/iterate.py --symbol MES --grid-json grid.json \
        --fixed-contracts 1 --out ...

OUTPUT: one row per (combo × vix-config) with screening metrics + MC bootstrap.
Writes ONLY to --out; never touches engine/data/gate_v2_verdicts/.
Screening only: this does NOT produce a gate-v2 verdict. Survivors must be
certified by the existing WFO runners (run_mes_trend_rank11.py etc.) on deep data.

RULES (jarvis-deep-validation skill + engine conventions):
  - Deep cache only (2015-01-01_2026-08-16_1h.csv); smoke truncates tail.
  - env -u PYTHONPATH -u PYTHONHOME when launched from the Hermes shell
    (PYTHONPATH poisoning breaks the engine venv).
  - Uses the REAL trend_signals.generate_sma_trend_signals + Backtester — never
    a hand-rolled signal (lookahead/contract violations).
  - fixed_contracts=1 is the equal-weight basis; default None = risk-based sizing
    (matches the certified MES rank11 champion). On low-ATR instruments (MGC)
    prefer --fixed-contracts 1 — ATR sizing inverts trend edge (MGC lesson).
  - MC uses bootstrap_pf on per-trade P&L (the same primitive the gate uses).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.backtester import Backtester  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults (mirror the certified rank11 champion wiring where applicable)
# ---------------------------------------------------------------------------
DEFAULT_GRID = {
    "MES": {
        "fast": [40, 45, 50, 55, 60, 65],
        "slow": [150, 200, 250],
        "atr_trail_mult": [1.5, 2.0, 2.5],
    },
    "MGC": {
        "fast": [40, 50, 60],
        "slow": [120, 200],
        "atr_trail_mult": [1.5, 2.0],
    },
    # Equities: SMA(12) champion is fast=12; grid tight around it on daily/1h.
    "SPY": {
        "fast": [8, 10, 12, 14],
        "slow": [40, 50, 60],
        "atr_trail_mult": [2.0, 2.5, 3.0],
    },
    "QQQ": {
        "fast": [8, 10, 12, 14],
        "slow": [40, 50, 60],
        "atr_trail_mult": [2.0, 2.5, 3.0],
    },
    "AAPL": {
        "fast": [8, 10, 12, 14],
        "slow": [40, 50, 60],
        "atr_trail_mult": [2.0, 2.5, 3.0],
    },
    "TSLA": {
        "fast": [8, 10, 12, 14],
        "slow": [40, 50, 60],
        "atr_trail_mult": [2.0, 2.5, 3.0],
    },
}
# NOTE: equity caches are the widest AVAILABLE files. SPY daily = 33y; QQQ/AAPL/TSLA
# daily + 1h are shallow (2y) — treat any equity screen as preliminary until deeper
# caches are fetched. The live scanner trades these on 1h, so 1h screens are the
# closest proxy; daily screens validate the daily rank runners, NOT the live loop.
CACHE_PATTERNS = {
    "MES": "backtest/cache/MES_2015-01-01_2026-08-16_1h.csv",
    "MGC": "backtest/cache/MGC_2015-01-01_2026-08-16_1h.csv",
    # Equity daily deep caches (2015-2026, 2,922 bars) fetched 2026-08-17.
    "SPY": "backtest/cache/SPY_2015-01-01_2026-08-17_1d.csv",
    "QQQ": "backtest/cache/QQQ_2015-01-01_2026-08-17_1d.csv",
    "AAPL": "backtest/cache/AAPL_2015-01-01_2026-08-17_1d.csv",
    "TSLA": "backtest/cache/TSLA_2015-01-01_2026-08-17_1d.csv",
}
CAPITAL = 50_000.0
SYMBOL_MULTIPLIER = {"MES": 5.0, "MGC": 10.0, "SPY": 1.0, "QQQ": 1.0, "AAPL": 1.0, "TSLA": 1.0}
# Champion wiring (run_mes_trend_rank11.py): risk-based sizing, 0.01 risk/trade.
CHAMPION_BT_ARGS = {
    "initial_capital": CAPITAL,
    "risk_per_trade": 0.01,
    "max_daily_loss": 0.02,
    "max_drawdown": 0.05,
    "t1_exit_pct": 0.50,
    "t2_exit_pct": 0.30,
}
COMMISSION = 0.62  # realistic tier (engine default)
SLIPPAGE_TICKS = 2.0
VIX_TIERS = ("Crisis", "HighVol", "MidVol", "LowVol")


def load_deep_cache(symbol: str, smoke: bool = False, cache_override: str | None = None) -> pd.DataFrame:
    """Load the deep cache; hard-fail if missing. Smoke truncates to tail.

    `cache_override` screens a non-default timeframe (e.g. the 15m/5m continuous
    caches) without editing CACHE_PATTERNS. The default remains the certified 1h
    deep cache, so an override is always an explicit, visible choice.
    """
    path = Path(cache_override) if cache_override else Path(CACHE_PATTERNS[symbol])
    if not path.exists():
        raise FileNotFoundError(
            f"Deep cache not found: {path}. Fetch deep data first "
            f"(see jarvis-deep-validation skill)."
        )
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    ts = pd.to_datetime(df[ts_col])
    # Normalize tz (some caches are tz-aware UTC; VIX reindex needs naive)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    if smoke:
        df = df.tail(2_000)  # ~3 months of 1h bars: fast wiring proof only
    span_years = max((df.index.max() - df.index.min()).days / 365.25, 1e-9)
    print(
        f"[{symbol}] {len(df)} bars | {df.index.min()} -> {df.index.max()} "
        f"| {span_years:.2f}y | {len(df) / span_years:,.0f} bars/yr | cache={path.name}"
    )
    return df


def load_vix(csv_path: str | None) -> pd.DataFrame | None:
    """Load VIX daily close. Accepts CSV with 'close' + date index, or yfinance.

    Auto-discovery (2026-08-17): when csv_path is None, look for the on-disk
    cache `backtest/cache/VIX_*.csv` (verified: VIX_1990-01-02_2026-08-17_1d.csv,
    9,224 bars) BEFORE falling back to yfinance. Prior to this, every VIX gate
    silently no-op'd when no CSV was given, making 'VIX-adjusted' runs vacuous.
    """
    if csv_path:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"VIX CSV not found: {path}")
        vix = pd.read_csv(path, index_col=0, parse_dates=True)
        vix.index = pd.to_datetime(vix.index).normalize()
        if "close" not in vix.columns:
            raise ValueError(f"VIX CSV must have a 'close' column; got {list(vix.columns)}")
        print(f"[VIX] {len(vix)} bars from CSV {path} | {vix.index.min().date()} -> {vix.index.max().date()}")
        return vix[["close"]]
    # Auto-discovery: on-disk cache first (avoids silent no-op and network).
    cache_dir = Path(__file__).resolve().parent / "cache"
    candidates = sorted(cache_dir.glob("VIX_*.csv"))
    if candidates:
        vix = pd.read_csv(candidates[-1], index_col=0, parse_dates=True)
        vix.index = pd.to_datetime(vix.index).normalize()
        if "close" in vix.columns:
            print(f"[VIX] auto-discovered {len(vix)} bars from {candidates[-1].name} "
                  f"| {vix.index.min().date()} -> {vix.index.max().date()}")
            return vix[["close"]]
    # Fallback: yfinance (same path as run_mes_trend_vix_rank1.py)
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit(
            "[VIX] no --vix-csv given, no VIX_*.csv cache found, and yfinance not installed. "
            "Provide --vix-csv or install yfinance."
        ) from exc
    print("[VIX] Downloading ^VIX daily via yfinance ...")
    vix = yf.download("^VIX", start="2015-01-01", progress=False, auto_adjust=True)
    if vix.empty:
        raise SystemExit("[VIX] yfinance returned empty data.")
    # yfinance >= 1.5 returns MultiIndex columns (('Close','^VIX'), ...) even for
    # a single ticker; flatten to level-0 names so `close` exists.
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = [str(c[0]).lower() for c in vix.columns]
    else:
        vix.columns = [str(c).lower() for c in vix.columns]
    vix.index = pd.to_datetime(vix.index).normalize()
    print(f"[VIX] {len(vix)} bars | {vix.index.min().date()} -> {vix.index.max().date()}")
    return vix[["close"]]


def vix_gate_smoke_assert(
    df: pd.DataFrame,
    symbol: str,
    vix_df: pd.DataFrame | None,
    vix_min: float,
    vix_max: float,
    vix_regime_block: tuple[str, ...] | None,
) -> None:
    """Assert that VIX gating actually filters — i.e. the gated run has fewer
    trades than the ungated run. If the gate is a no-op (trade counts identical),
    it means VIX data is missing or the gate is not wired, and every 'VIX-adjusted'
    result is vacuous.

    2026-08-18: this assertion exists because before the VIX cache existed on disk,
    every VIX-gated run silently no-op'd — all prior 'VIX-adjusted' results were
    meaningless. This guard makes that failure mode LOUD.
    """
    if vix_df is None:
        if vix_min > 0.0 or vix_max < 999.0 or vix_regime_block:
            raise SystemExit(
                "[VIX SMOKE] VIX gate requested (vix-min/vix-max/vix-regimes) but "
                "vix_df is None — gate is a NO-OP. All 'VIX-adjusted' results would "
                "be vacuous. Aborting. Check that load_vix() found the cache."
            )
        return  # No gate requested, no assertion needed.

    # Run the SAME combo (first grid point) ungated vs gated, compare trade counts.
    grid = DEFAULT_GRID[symbol]
    fast, slow, atr_trail_mult = grid["fast"][0], grid["slow"][0], grid["atr_trail_mult"][0]
    # Ungated baseline
    ungated = run_combo(
        df, symbol, fast, slow, atr_trail_mult,
        vix_df=None, vix_min=0.0, vix_max=999.0,
        vix_regime_block=None, fixed_contracts=1,
    )
    gated = run_combo(
        df, symbol, fast, slow, atr_trail_mult,
        vix_df=vix_df, vix_min=vix_min, vix_max=vix_max,
        vix_regime_block=vix_regime_block, fixed_contracts=1,
    )
    ungated_trades = ungated["total_trades"]
    gated_trades = gated["total_trades"]
    print(
        f"[VIX SMOKE] ungated trades={ungated_trades} vs gated trades={gated_trades} "
        f"(vix_min={vix_min}, vix_max={vix_max}, block={vix_regime_block})"
    )
    if ungated_trades > 0 and gated_trades == ungated_trades:
        raise SystemExit(
            f"[VIX SMOKE] FAIL: VIX gate did not filter any trades "
            f"(ungated={ungated_trades} == gated={gated_trades}). "
            f"The gate is a no-op — VIX data may not be aligned to the price series. "
            f"Aborting to prevent vacuous 'VIX-adjusted' results."
        )
    if ungated_trades == 0 and gated_trades == 0:
        print("[VIX SMOKE] WARNING: both ungated and gated produced 0 trades — "
              "cannot verify gate filtering (combo has no trades to filter).")
        return
    print(f"[VIX SMOKE] PASS: gate filtered {ungated_trades - gated_trades} trades.")


def run_combo(
    df: pd.DataFrame,
    symbol: str,
    fast: int,
    slow: int,
    atr_trail_mult: float,
    vix_df: pd.DataFrame | None,
    vix_min: float,
    vix_max: float,
    vix_regime_block: tuple[str, ...] | None,
    fixed_contracts: int | None,
) -> dict:
    """Run one (params × vix-config) combo on the supplied bars. Real engine only."""
    df_sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        vix_df=vix_df,
        vix_min=vix_min,
        vix_max=vix_max,
        vix_regime_block=vix_regime_block,
    )
    bt_args = dict(CHAMPION_BT_ARGS)
    if fixed_contracts is not None:
        bt_args["fixed_contracts"] = fixed_contracts
    bt = Backtester(
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
        **bt_args,
    )
    res = bt.run(df_sig, symbol=symbol, multiplier=SYMBOL_MULTIPLIER[symbol])
    pnls = [t.pnl for t in res.trades]
    return {
        "symbol": symbol,
        "fast": fast,
        "slow": slow,
        "atr_trail_mult": atr_trail_mult,
        "vix_min": vix_min,
        "vix_max": vix_max,
        "vix_regime_block": list(vix_regime_block) if vix_regime_block else None,
        "fixed_contracts": fixed_contracts,
        "total_trades": res.total_trades,
        "win_rate": round(res.win_rate, 4),
        "profit_factor": round(res.profit_factor, 4),
        "total_pnl": round(res.total_pnl, 2),
        "max_drawdown_pct": round(res.max_drawdown_pct, 4),
        "sharpe_ratio": round(res.sharpe_ratio, 4),
        "n_pnl_samples": len(pnls),
    }


def run_combo_with_pnls(
    df: pd.DataFrame,
    symbol: str,
    fast: int,
    slow: int,
    atr_trail_mult: float,
    vix_df: pd.DataFrame | None,
    vix_min: float,
    vix_max: float,
    vix_regime_block: tuple[str, ...] | None,
    fixed_contracts: int | None,
    mc_resamples: int,
    mc_seed: int,
    strategy: str = "trend",
    extra: dict | None = None,
) -> dict:
    """run_combo + MC bootstrap in one call; returns a full row dict.

    strategy: "trend" (SMA, existing) | "tpv" | "mrb". extra carries
    strategy-specific kwargs (e.g. MRB bb_std / max_hold_bars).
    """
    from backtest.monte_carlo import bootstrap_pf

    if strategy == "tpv":
        from backtest.composite_strategies import generate_trend_pullback_signals
        df_sig = generate_trend_pullback_signals(
            df, fast_ema=fast, slow_ema=slow, atr_trail_mult=atr_trail_mult,
            vix_df=vix_df, vix_min=vix_min, vix_max=vix_max,
            vix_regime_block=vix_regime_block,
        )
    elif strategy == "mrb":
        from backtest.composite_strategies import generate_guarded_meanrev_signals
        ex = extra or {}
        df_sig = generate_guarded_meanrev_signals(
            df,
            bb_std=float(ex.get("bb_std", 2.0)),
            atr_mult=atr_trail_mult,
            max_hold_bars=int(ex.get("max_hold_bars", 6)),
            vix_df=vix_df, vix_min=vix_min, vix_max=vix_max,
            vix_regime_block=vix_regime_block or ("Crisis", "HighVol"),
        )
    else:
        df_sig = generate_sma_trend_signals(
            df,
            fast=fast,
            slow=slow,
            atr_trail_mult=atr_trail_mult,
            vix_df=vix_df,
            vix_min=vix_min,
            vix_max=vix_max,
            vix_regime_block=vix_regime_block,
        )
    bt_args = dict(CHAMPION_BT_ARGS)
    if fixed_contracts is not None:
        bt_args["fixed_contracts"] = fixed_contracts
    bt = Backtester(
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
        **bt_args,
    )
    res = bt.run(df_sig, symbol=symbol, multiplier=SYMBOL_MULTIPLIER[symbol])
    pnls = [t.pnl for t in res.trades]
    # Honest CAGR from the actual equity span (PF/Sharpe alone hide economic triviality).
    cagr = 0.0
    if len(pnls) > 0 and res.start_date and res.end_date:
        try:
            span_days = (pd.Timestamp(res.end_date) - pd.Timestamp(res.start_date)).days
            years = span_days / 365.25
            if years > 0:
                final = float(res.initial_capital) + float(res.total_pnl)
                if final > 0:
                    cagr = (final / float(res.initial_capital)) ** (1.0 / years) - 1.0
        except (ValueError, TypeError, ZeroDivisionError):
            cagr = 0.0
    row = {
        "symbol": symbol,
        "strategy": strategy,
        "fast": fast,
        "slow": slow,
        "atr_trail_mult": atr_trail_mult,
        "vix_min": vix_min,
        "vix_max": vix_max,
        "vix_regime_block": list(vix_regime_block) if vix_regime_block else None,
        "fixed_contracts": fixed_contracts,
        "total_trades": res.total_trades,
        "win_rate": round(res.win_rate, 4),
        "profit_factor": round(res.profit_factor, 4),
        "total_pnl": round(res.total_pnl, 2),
        "max_drawdown_pct": round(res.max_drawdown_pct, 4),
        # NOTE 2026-08-17: res.sharpe_ratio is now HONEST (observed trades/yr
        # annualization, metrics.py correction). No MES config has true Sharpe > 1.
        "sharpe_ratio": round(res.sharpe_ratio, 4),
        "annualization_trades_per_year": round(float(getattr(res, "annualization_trades_per_year", 0.0)), 2),
        "cagr_pct": round(cagr * 100.0, 4),
        "n_pnl_samples": len(pnls),
    }
    if len(pnls) >= 3:
        mc = bootstrap_pf(pnls, n_resamples=mc_resamples, seed=mc_seed)
        row["mc_median_pf"] = round(float(mc["median_pf"]), 4)
        row["mc_pf_ci_95_low"] = round(float(mc["pf_ci_95_low"]), 4)
        row["mc_p_positive_edge"] = round(float(mc["p_positive_edge"]), 4)
    else:
        row["mc_median_pf"] = None
        row["mc_pf_ci_95_low"] = None
        row["mc_p_positive_edge"] = None
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="JARVIS batch iteration harness")
    ap.add_argument("--symbol", choices=sorted(CACHE_PATTERNS), default="MES")
    ap.add_argument("--strategy", choices=["trend", "tpv", "mrb"], default="trend",
                    help="signal family: trend (SMA) | tpv (trend-pullback) | mrb (guarded mean-reversion)")
    ap.add_argument("--mrb-bb-std", type=float, default=2.0, help="MRB Bollinger width in std")
    ap.add_argument("--mrb-max-hold", type=int, default=6, help="MRB max holding bars (time-stop)")
    ap.add_argument("--smoke", action="store_true", help="one combo, tail 2000 bars")
    ap.add_argument("--cache", type=str, default=None,
                    help="override the cache path (e.g. a 15m/5m continuous file). "
                         "Default is the certified 1h deep cache for --symbol.")
    ap.add_argument("--grid-json", type=str, default=None, help="custom grid JSON")
    ap.add_argument("--vix-csv", type=str, default=None, help="VIX daily CSV path")
    ap.add_argument("--vix-min", type=float, default=0.0, help="VIX lower bound (inclusive)")
    ap.add_argument("--vix-max", type=float, default=999.0, help="VIX upper bound (inclusive)")
    ap.add_argument("--vix-regimes", type=str, default=None,
                    help="comma-separated tier set(s) to block, e.g. Crisis,HighVol")
    ap.add_argument("--fixed-contracts", type=int, default=None,
                    help="equal-weight basis; None = risk-based (champion)")
    ap.add_argument("--mc-resamples", type=int, default=2_000)
    ap.add_argument("--mc-seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=None, help="results JSON path")
    args = ap.parse_args()

    df = load_deep_cache(args.symbol, smoke=args.smoke, cache_override=args.cache)

    grid = DEFAULT_GRID[args.symbol]
    if args.grid_json:
        grid = json.loads(Path(args.grid_json).read_text())

    # VIX regime sets: None (no block) + one set per provided tier-set string.
    vix_regime_sets: list[tuple[str, ...] | None] = [None]
    if args.vix_regimes:
        tiers = tuple(t.strip() for t in args.vix_regimes.split(",") if t.strip())
        bad = [t for t in tiers if t not in VIX_TIERS]
        if bad:
            raise SystemExit(f"Unknown VIX tiers: {bad}; valid: {VIX_TIERS}")
        vix_regime_sets = [tiers]

    vix_df = load_vix(args.vix_csv) if (args.vix_min > 0.0 or args.vix_max < 999.0 or args.vix_regimes) else None

    # VIX gate smoke assertion: prove the gate actually filters before running the
    # full grid. Prevents vacuous "VIX-adjusted" results (the 2026-08-17 bug).
    if not args.smoke:
        vix_gate_smoke_assert(df, args.symbol, vix_df, args.vix_min, args.vix_max,
                              vix_regime_sets[0] if vix_regime_sets else None)

    # Smoke: force single combo so the wiring proof is fast.
    combos = list(itertools.product(grid["fast"], grid["slow"], grid["atr_trail_mult"]))
    if args.smoke:
        combos = [combos[0]]
        vix_regime_sets = [None]
        print("[SMOKE] single combo, tail window — wiring proof only")

    rows: list[dict] = []
    extra = {"bb_std": args.mrb_bb_std, "max_hold_bars": args.mrb_max_hold}
    for fast, slow, atr_trail_mult in combos:
        for regime_block in vix_regime_sets:
            rows.append(run_combo_with_pnls(
                df, args.symbol, fast, slow, atr_trail_mult,
                vix_df, args.vix_min, args.vix_max, regime_block,
                args.fixed_contracts, args.mc_resamples, args.mc_seed,
                strategy=args.strategy, extra=extra,
            ))
            print(f"  [{len(rows)}/{len(combos)*len(vix_regime_sets)}] fast={fast} slow={slow} "
                  f"atr={atr_trail_mult} vix_block={regime_block} "
                  f"trades={rows[-1]['total_trades']} pf={rows[-1]['profit_factor']}")

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol,
        "strategy": args.strategy,
        "smoke": args.smoke,
        "cache": args.cache or CACHE_PATTERNS[args.symbol],
        "cache_is_override": bool(args.cache),
        "n_bars": len(df),
        "span_years": round(max((df.index.max() - df.index.min()).days / 365.25, 1e-9), 4),
        "vix_config": {
            "min": args.vix_min,
            "max": args.vix_max,
            "regime_sets": vix_regime_sets,
        },
        "fixed_contracts": args.fixed_contracts,
        "mc": {"n_resamples": args.mc_resamples, "seed": args.mc_seed},
        "n_rows": len(rows),
        "rows": rows,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, indent=2, default=str))
        print(f"\nWrote {len(rows)} rows -> {out_path}")
    else:
        print(json.dumps(doc, indent=2, default=str))

    # Screening quick-read (best by mc_p_positive_edge, min trades)
    qualified = [r for r in rows if r["total_trades"] >= 10 and (r.get("mc_p_positive_edge") or 0) >= 0.6]
    qualified.sort(key=lambda r: r.get("mc_p_positive_edge") or 0, reverse=True)
    print(f"\n=== Screening shortlist (>=10 trades, p_positive_edge>=0.6): {len(qualified)} ===")
    for r in qualified[:10]:
        print(f"  fast={r['fast']} slow={r['slow']} atr={r['atr_trail_mult']} "
              f"vix_block={r['vix_regime_block']} trades={r['total_trades']} "
              f"pf={r['profit_factor']} p_edge={r['mc_p_positive_edge']} dd={r['max_drawdown_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
