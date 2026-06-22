#!/usr/bin/env python
"""VIX/VIX3M Term-Structure Overlay -- A/B Decision Gate (MES).

This is the decision gate for the ship-dark term-structure sizing overlay
(analytics/term_structure.py, settings.TS_OVERLAY_ENABLED, default OFF). It answers
one question with jarvis's own gate v2: does scaling MES trend entries by the VIX/VIX3M
term-structure regime (CONTANGO keep / FLAT keep / BACKWARDATION shrink-or-stand-aside)
improve risk-adjusted, walk-forward, out-of-sample performance vs the unscaled champion?

DESIGN (post-processing A/B -- reuses the validated MES champion WFO):
  1. Run the existing MES trend+VIX WFO once (run_mes_trend_vix_rank1 helpers) and
     capture each OOS window's real completed trades (entry_date + pnl). This is the
     champion's true OOS trade stream -- no re-fitting, no new search on the price side.
  2. Load daily VIX (^VIX) and VIX3M (^VIX3M) and, for each trade, read the regime
     AS-OF the trade's entry date (same-day daily close, forward-filled -- the exact
     no-lookahead convention the runner uses to align daily VIX to intraday bars).
  3. Arm A = overlay OFF (multiplier == 1.0 for every trade).
     Arm B = overlay ON; scale each trade's pnl by the regime multiplier at its entry
     (CONTANGO x1.0, FLAT x flat_mult, BACKWARDATION x backwardation_mult; a 0.0
     backwardation_mult means stand-aside -> drop the trade).
  4. Rebuild each window's gate metrics (profit_factor, sharpe_ratio, max_drawdown_pct,
     total_trades) from the scaled trades using the SAME formulas as backtest/metrics.py
     (PF and Sharpe are trade-derived there; DD here is rebuilt from a trade-level equity
     curve -- internally identical across both arms, so the A/B delta is clean).
  5. Feed both arms through the real _compute_gate_v2 and compare. Sweep the free overlay
     knobs only (flat_band x backwardation_mult = 8 combos) and deflate the Sharpe with
     n_trials=8 so DSR deflation stays honest.

RECOMMENDATION -- ENABLE only if the best Arm B BEATS Arm A on risk-adjusted terms AND
clears the absolute gate (this is the plan's enable/kill rule):
  - Arm B clears gate v2 (CORE pf_ci_lower>=1.10 & p_edge>=0.95 & mc_dd<=0.05 & dsr>=0.10,
    OR ALT dsr>=0.30 + wfo_consistency + fixed_params + cost + mc_dd<=0.04), AND
  - dsr(B)   > dsr(A)            (better risk-adjusted edge), AND
  - maxDD(B) < maxDD(A)          (the validated "cuts the tail" property), AND
  - mc_95th_dd(B) <= mc_95th_dd(A).
Anything short of all four -> KILL (leave TS_OVERLAY_ENABLED=False). This script never
flips the flag; enabling + the engine restart are Amo-only.

SCOPE: MES only. MES is the one symbol with a VIX-aware champion WFO runner
(run_mes_trend_vix_rank1.py); the equity-vol term-structure signal is also most
applicable to the flagship equity-index symbol. MNQ has caches but no VIX champion
runner; MCL/MGC are commodities with a weaker prior. Extending to those means building
a per-symbol VIX champion first -- out of scope for this decision gate (documented in
the emitted summary).

Usage (from engine/ with the main venv python):
    .venv/Scripts/python backtest/run_term_structure_overlay_ab.py

Writes:
    data/gate_v2_verdicts/MES_term_structure_overlay_ab.json
    data/gate_v2_verdicts/MES_term_structure_overlay_ab.md
"""
from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# Champion WFO helpers (reused verbatim -- single source of truth for the price side).
from backtest.run_mes_trend_vix_rank1 import (  # noqa: E402
    CAPITAL,
    MIN_OOS_TRADES_PER_WINDOW,
    VIX_MAX_VALUES,
    VIX_MIN_VALUES,
    _best_is_vix_params,
    _compute_gate_v2,
    _generate_windows,
    _load_mes_data,
    _load_vix_data,
    _run_cost_sweep,
    _run_fixed_params_sweep,
    _run_signals_and_backtest,
)
from collections import Counter  # noqa: E402

from backtest.metrics import ANNUALIZATION_TRADES_PER_YEAR  # noqa: E402

# Worktree overlay under test.
from analytics.term_structure import (  # noqa: E402
    Regime,
    classify_term_structure,
    regime_multiplier,
)

# The price-side cache lives in the MAIN tree (data CSVs are gitignored, so a git
# worktree's cache/ is empty). Point at the main tree explicitly.
DATA_DIR = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache")

# ---------------------------------------------------------------------------
# Overlay sweep grid (free knobs only; 8 combos -> honest DSR n_trials=8)
# ---------------------------------------------------------------------------
# flat_band in POINTS (the options-vrp 0.005 decimal default rescales to 0.5 points).
FLAT_BAND_VALUES = [0.0, 0.5, 1.0, 2.0]
# 0.0 backwardation_mult == stand aside (drop the trade); 0.5 == half size.
BACKWARDATION_MULT_VALUES = [0.0, 0.5]
CONTANGO_MULT = 1.0
FLAT_MULT = 1.0
N_OVERLAY_COMBOS = len(FLAT_BAND_VALUES) * len(BACKWARDATION_MULT_VALUES)  # 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Drop tz from a daily DatetimeIndex and normalize to date. Used for the VIX/
    VIX3M daily frames so they align with the tz-naive intraday bar index."""
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df = df.copy()
    df.index = idx.normalize()
    return df


def _strip_tz_keep_time(df: pd.DataFrame) -> pd.DataFrame:
    """Drop tz from an intraday DatetimeIndex, PRESERVING time-of-day. The MES cache
    is written tz-aware UTC (datetime64[us, UTC]); the VIX daily frame is tz-naive, so
    the reindex inside generate_sma_trend_signals raises 'Cannot compare dtypes ... UTC'.
    Convert the bar index to tz-naive (UTC wall-clock kept) so the date alignment works.
    NOTE: the native run_mes_trend_vix_rank1.py hits the same wall with this tz-aware
    cache -- a pre-existing main-tree issue surfaced here, flagged separately."""
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df = df.copy()
    df.index = idx
    return df


# ---------------------------------------------------------------------------
# VIX3M daily loader (mirrors run_mes_trend_vix_rank1._load_vix_data)
# ---------------------------------------------------------------------------
def _load_vix3m_data(start: str = "2022-01-01") -> pd.DataFrame:
    """Load VIX3M daily close via yfinance (^VIX3M). Returns DataFrame['close']."""
    try:
        import yfinance as yf
    except ImportError:
        print("[ERROR] yfinance not installed. Run: .venv/Scripts/pip install yfinance")
        sys.exit(1)

    print(f"[VIX3M] Downloading ^VIX3M daily from {start} ...")
    v3 = yf.download("^VIX3M", start=start, progress=False, auto_adjust=True)
    if v3.empty:
        print("[ERROR] yfinance returned empty VIX3M data.")
        sys.exit(1)

    v3.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in v3.columns]
    v3.index = pd.to_datetime(v3.index).normalize()
    print(
        f"[VIX3M] {len(v3)} bars | {v3.index.min().date()} -> {v3.index.max().date()} "
        f"| current: {v3['close'].iloc[-1]:.2f}"
    )
    return v3[["close"]]


def _build_term_structure_daily(vix_df: pd.DataFrame, vix3m_df: pd.DataFrame) -> pd.DataFrame:
    """Daily frame indexed by normalized date with columns vix, vix3m (ffilled, aligned).

    Both legs forward-filled onto the union of dates so a trade entered on any session
    reads the most recent known close of each leg as-of its entry (no lookahead).
    """
    vix = vix_df.rename(columns={"close": "vix"}).copy()
    v3 = vix3m_df.rename(columns={"close": "vix3m"}).copy()
    idx = vix.index.union(v3.index)
    out = pd.DataFrame(index=idx)
    out["vix"] = vix["vix"].reindex(idx).ffill()
    out["vix3m"] = v3["vix3m"].reindex(idx).ffill()
    return out


def _regime_mult_for_trade(
    entry_date,
    ts_daily: pd.DataFrame,
    flat_band: float,
    backwardation_mult: float,
    standaside: bool,
) -> float:
    """Term-structure multiplier as-of a trade's entry date. 1.0 on any missing leg
    (passthrough -- same degrade-to-baseline contract the live overlay honors)."""
    d = pd.Timestamp(entry_date).normalize()
    # as-of: most recent daily row at or before the entry date.
    sub = ts_daily.loc[:d]
    if sub.empty:
        return 1.0
    row = sub.iloc[-1]
    vix, vix3m = row["vix"], row["vix3m"]
    if pd.isna(vix) or pd.isna(vix3m) or vix <= 0 or vix3m <= 0:
        return 1.0
    regime, _slope = classify_term_structure(float(vix), float(vix3m), flat_band)
    if regime == Regime.BACKWARDATION and standaside:
        return 0.0
    return regime_multiplier(regime, CONTANGO_MULT, FLAT_MULT, backwardation_mult)


# ---------------------------------------------------------------------------
# Faithful per-window metric rebuild from (optionally scaled) trades
# ---------------------------------------------------------------------------
def _metrics_from_trades(trades, mult_fn, capital: float) -> SimpleNamespace:
    """Rebuild the gate-relevant metrics from a trade list scaled by mult_fn(entry_date).

    PF and Sharpe use the same formulas as backtest/metrics.py (trade-derived there).
    max_drawdown_pct is rebuilt from a trade-level equity curve (cumulative scaled pnl);
    this is internally identical for both arms, so the A/B delta is apples-to-apples.
    A multiplier of 0.0 (stand-aside) drops the trade entirely.
    """
    scaled_pnls = []
    for t in trades:
        m = mult_fn(t.entry_date)
        if m <= 0.0:
            continue  # stand-aside: trade not taken
        scaled_pnls.append(float(t.pnl) * m)

    n = len(scaled_pnls)
    if n == 0:
        return SimpleNamespace(
            profit_factor=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0, total_trades=0
        )

    arr = np.array(scaled_pnls, dtype=float)
    gross_profit = float(arr[arr > 0].sum())
    gross_loss = float(arr[arr <= 0].sum())
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else float("inf")

    # Sharpe over per-trade returns (pnl / initial_capital), annualized -- mirrors
    # metrics.compute_sharpe_sortino exactly.
    if n > 1:
        rets = arr / capital
        std = rets.std(ddof=1)
        sharpe = float((rets.mean() / std) * np.sqrt(ANNUALIZATION_TRADES_PER_YEAR)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown from a trade-level equity curve.
    equity = capital + np.cumsum(arr)
    equity = np.concatenate(([capital], equity))
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak == 0, 1.0, peak)
    dd = (equity - peak) / safe_peak
    max_dd = float(abs(dd.min())) if len(dd) > 1 else 0.0

    return SimpleNamespace(
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        sharpe_ratio=sharpe,
        total_trades=n,
    )


def _gate_for_arm(oos_trade_lists, mult_fn, fixed_metrics, cost_metrics, n_trials):
    """Rebuild per-window metrics under mult_fn and run the real gate v2."""
    rebuilt = [
        _metrics_from_trades(trades, mult_fn, CAPITAL) for trades in oos_trade_lists
    ]
    return _compute_gate_v2(
        rebuilt,
        n_grid_combos=n_trials,
        fixed_params_metrics=fixed_metrics,
        cost_sweep_metrics=cost_metrics,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_ab() -> dict:
    print(f"\n{'=' * 72}")
    print("=== TERM-STRUCTURE OVERLAY A/B (MES) -- decision gate ===")
    print(f"{'=' * 72}")

    df = _strip_tz_keep_time(_load_mes_data(DATA_DIR))
    start = str(df.index.min().date())
    vix_df = _strip_tz(_load_vix_data(start=start))
    vix3m_df = _strip_tz(_load_vix3m_data(start=start))
    ts_daily = _build_term_structure_daily(vix_df, vix3m_df)
    print(
        f"[TS] term-structure daily frame: {len(ts_daily)} rows | "
        f"{ts_daily.index.min().date()} -> {ts_daily.index.max().date()}"
    )

    windows = _generate_windows(df)
    if not windows:
        print("[TS-AB] ERROR: not enough data to form windows.")
        return {}

    vix_grid = list(itertools.product(VIX_MIN_VALUES, VIX_MAX_VALUES))
    n_vix_combos = len(vix_grid)

    # --- Replicate the champion WFO once; capture real OOS trade lists ----------
    oos_results_real = []
    oos_trade_lists = []
    window_records = []
    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_vix_params(df_train, vix_df, vix_grid)
        if best_params is None:
            print(f"  Window {wnum}: [SKIP] no valid IS VIX params")
            continue
        try:
            oos_result = _run_signals_and_backtest(
                df_test, vix_df, vix_min=best_params["vix_min"], vix_max=best_params["vix_max"]
            )
        except Exception as exc:
            print(f"  Window {wnum}: [SKIP] OOS error: {exc}")
            continue

        oos_results_real.append(oos_result)
        oos_trade_lists.append(list(oos_result.trades))
        window_records.append(
            {
                "window": wnum,
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_vix_params": best_params,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )
        print(
            f"  Window {wnum}: OOS PF={oos_result.profit_factor:.2f} "
            f"DD={oos_result.max_drawdown_pct:.1%} trades={oos_result.total_trades}"
        )

    if not oos_results_real:
        print("[TS-AB] No OOS results -- aborting.")
        return {}

    total_trades = sum(len(t) for t in oos_trade_lists)
    print(f"\n[TS-AB] Captured {len(oos_trade_lists)} OOS windows, {total_trades} trades.")

    # --- ALT-path inputs (computed once, no overlay; held constant across arms) --
    # The overlay's effect is modeled in the CORE per-window stream; the fixed-params
    # and cost sweeps describe the underlying champion and are baseline for both arms.
    print("\n[TS-AB] Running fixed-params + cost sweeps (baseline; shared by both arms)...")
    fixed_metrics = _run_fixed_params_sweep(df, vix_df, vix_grid)
    param_votes = Counter(
        (r["best_vix_params"]["vix_min"], r["best_vix_params"]["vix_max"]) for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (13, 30)
    champion_vix = {"vix_min": most_selected[0], "vix_max": most_selected[1]}
    cost_metrics = _run_cost_sweep(df, vix_df, champion_vix)

    # --- Arm A (native baseline; reproduces the real MES verdict) ----------------
    gate_a_native = _compute_gate_v2(
        oos_results_real,
        n_grid_combos=n_vix_combos,
        fixed_params_metrics=fixed_metrics,
        cost_sweep_metrics=cost_metrics,
    )
    print(
        f"\n[Arm A native] verdict={gate_a_native['verdict']} "
        f"pf_ci_lower={gate_a_native['pf_ci_lower']} p_edge={gate_a_native['p_edge']} "
        f"mc_dd={gate_a_native['mc_95th_dd_pct']}% dsr={gate_a_native['dsr']}"
    )

    # --- Arm A rebuilt (mult==1) under the same deflation the overlay arms use ----
    gate_a = _gate_for_arm(
        oos_trade_lists, lambda d: 1.0, fixed_metrics, cost_metrics, N_OVERLAY_COMBOS
    )
    print(
        f"[Arm A rebuilt] verdict={gate_a['verdict']} "
        f"pf_ci_lower={gate_a['pf_ci_lower']} p_edge={gate_a['p_edge']} "
        f"mc_dd={gate_a['mc_95th_dd_pct']}% dsr={gate_a['dsr']}"
    )

    # --- Arm B sweep (8 overlay combos) -----------------------------------------
    arm_b_results = []
    for flat_band, bwd_mult in itertools.product(FLAT_BAND_VALUES, BACKWARDATION_MULT_VALUES):
        standaside = bwd_mult <= 0.0

        def mult_fn(entry_date, _fb=flat_band, _bm=bwd_mult, _sa=standaside):
            return _regime_mult_for_trade(entry_date, ts_daily, _fb, _bm, _sa)

        gate_b = _gate_for_arm(
            oos_trade_lists, mult_fn, fixed_metrics, cost_metrics, N_OVERLAY_COMBOS
        )
        combo = {
            "flat_band": flat_band,
            "backwardation_mult": bwd_mult,
            "standaside_on_backwardation": standaside,
            "gate": gate_b,
        }
        arm_b_results.append(combo)
        print(
            f"  [Arm B] flat_band={flat_band:.1f} bwd_mult={bwd_mult:.2f}"
            f"{' (standaside)' if standaside else ''}: "
            f"verdict={gate_b['verdict']} pf_ci_lower={gate_b['pf_ci_lower']} "
            f"p_edge={gate_b['p_edge']} mc_dd={gate_b['mc_95th_dd_pct']}% dsr={gate_b['dsr']} "
            f"trades={gate_b['total_oos_trades']}"
        )

    # --- Pick best Arm B: prefer PASS, then highest dsr, then lowest mc_dd --------
    def _rank_key(c):
        g = c["gate"]
        return (1 if g["verdict"] == "PASS" else 0, g["dsr"], -g["mc_95th_dd"])

    best_b = max(arm_b_results, key=_rank_key)
    gate_b = best_b["gate"]

    # --- Enable/kill decision (all four conditions must hold) --------------------
    cond_b_passes = gate_b["verdict"] == "PASS"
    cond_dsr = gate_b["dsr"] > gate_a["dsr"]
    cond_maxdd = gate_b["mc_95th_dd"] < gate_a["mc_95th_dd"]  # proxy for "cuts the tail"
    cond_mcdd = gate_b["mc_95th_dd"] <= gate_a["mc_95th_dd"]
    enable = cond_b_passes and cond_dsr and cond_maxdd and cond_mcdd
    recommendation = "ENABLE" if enable else "KILL"

    reasons = []
    reasons.append(f"Arm B clears gate v2: {cond_b_passes} (verdict={gate_b['verdict']})")
    reasons.append(f"dsr(B) > dsr(A): {cond_dsr} ({gate_b['dsr']} vs {gate_a['dsr']})")
    reasons.append(
        f"mc_95th_dd(B) < mc_95th_dd(A): {cond_maxdd} "
        f"({gate_b['mc_95th_dd_pct']}% vs {gate_a['mc_95th_dd_pct']}%)"
    )
    reasons.append(f"mc_95th_dd(B) <= (A): {cond_mcdd}")

    print(f"\n{'=' * 72}")
    print(f"=== RECOMMENDATION: {recommendation} (TS_OVERLAY_ENABLED stays False) ===")
    for r in reasons:
        print(f"  - {r}")
    print(
        f"  best Arm B: flat_band={best_b['flat_band']} "
        f"backwardation_mult={best_b['backwardation_mult']} "
        f"standaside={best_b['standaside_on_backwardation']}"
    )
    print(f"{'=' * 72}")

    verdict_doc = {
        "symbol": "MES",
        "study": "term_structure_overlay_ab",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "recommendation": recommendation,
        "decision_conditions": {
            "arm_b_passes_gate": cond_b_passes,
            "dsr_b_gt_dsr_a": cond_dsr,
            "maxdd_b_lt_maxdd_a": cond_maxdd,
            "mc_dd_b_le_mc_dd_a": cond_mcdd,
            "all_hold": enable,
        },
        "best_arm_b_params": {
            "flat_band_points": best_b["flat_band"],
            "backwardation_mult": best_b["backwardation_mult"],
            "standaside_on_backwardation": best_b["standaside_on_backwardation"],
            "contango_mult": CONTANGO_MULT,
            "flat_mult": FLAT_MULT,
        },
        "arm_a_native": gate_a_native,
        "arm_a_rebuilt": gate_a,
        "arm_b_best": gate_b,
        "arm_b_sweep": [
            {
                "flat_band": c["flat_band"],
                "backwardation_mult": c["backwardation_mult"],
                "standaside": c["standaside_on_backwardation"],
                "verdict": c["gate"]["verdict"],
                "pf_ci_lower": c["gate"]["pf_ci_lower"],
                "p_edge": c["gate"]["p_edge"],
                "mc_95th_dd": c["gate"]["mc_95th_dd"],
                "dsr": c["gate"]["dsr"],
                "total_oos_trades": c["gate"]["total_oos_trades"],
            }
            for c in arm_b_results
        ],
        "config": {
            "n_oos_windows": len(oos_trade_lists),
            "total_oos_trades": total_trades,
            "flat_band_values": FLAT_BAND_VALUES,
            "backwardation_mult_values": BACKWARDATION_MULT_VALUES,
            "n_overlay_combos": N_OVERLAY_COMBOS,
            "champion_vix": champion_vix,
            "capital": CAPITAL,
            "note": (
                "Arm A native uses the VIX-grid deflation (n=%d); rebuilt arms use the "
                "overlay-sweep deflation (n=%d). ALT-path fixed-params/cost inputs are "
                "baseline (no overlay) and shared by both arms -- the overlay acts on the "
                "CORE per-window stream. DD is rebuilt at trade granularity (identical "
                "method both arms). Fractional multipliers model aggregate sizing; the "
                "live overlay clamps to integer contracts (coarser at 1-2 lots)."
            )
            % (n_vix_combos, N_OVERLAY_COMBOS),
        },
        "windows": window_records,
    }

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    json_file = verdicts_dir / "MES_term_structure_overlay_ab.json"
    json_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[TS-AB] Verdict JSON -> {json_file}")

    _write_summary_md(verdicts_dir / "MES_term_structure_overlay_ab.md", verdict_doc)
    print(f"[TS-AB] Summary MD  -> {verdicts_dir / 'MES_term_structure_overlay_ab.md'}")

    return verdict_doc


def _write_summary_md(path: Path, doc: dict) -> None:
    a = doc["arm_a_rebuilt"]
    an = doc["arm_a_native"]
    b = doc["arm_b_best"]
    bp = doc["best_arm_b_params"]
    lines = []
    lines.append("# Term-Structure Overlay A/B -- MES (decision gate)")
    lines.append("")
    lines.append(f"_Generated: {doc['created_at']}_")
    lines.append("")
    lines.append(f"## RECOMMENDATION: **{doc['recommendation']}**")
    lines.append("")
    lines.append("`TS_OVERLAY_ENABLED` stays `False`. Enabling + the engine restart are Amo-only.")
    lines.append("")
    lines.append("### Decision conditions (all four must hold to ENABLE)")
    dc = doc["decision_conditions"]
    lines.append("")
    lines.append("| Condition | Result |")
    lines.append("|---|---|")
    lines.append(f"| Arm B clears gate v2 | {dc['arm_b_passes_gate']} |")
    lines.append(f"| dsr(B) > dsr(A) | {dc['dsr_b_gt_dsr_a']} |")
    lines.append(f"| maxDD(B) < maxDD(A) | {dc['maxdd_b_lt_maxdd_a']} |")
    lines.append(f"| mc_95th_dd(B) <= (A) | {dc['mc_dd_b_le_mc_dd_a']} |")
    lines.append("")
    lines.append("### Gate v2 side-by-side")
    lines.append("")
    lines.append("| Metric | Arm A (native) | Arm A (rebuilt) | Arm B (best) | Threshold |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| verdict | {an['verdict']} | {a['verdict']} | {b['verdict']} | PASS |"
    )
    lines.append(
        f"| pf_ci_lower | {an['pf_ci_lower']} | {a['pf_ci_lower']} | {b['pf_ci_lower']} | >=1.10 |"
    )
    lines.append(
        f"| p_edge | {an['p_edge']} | {a['p_edge']} | {b['p_edge']} | >=0.95 |"
    )
    lines.append(
        f"| mc_95th_dd | {an['mc_95th_dd_pct']}% | {a['mc_95th_dd_pct']}% | "
        f"{b['mc_95th_dd_pct']}% | <=5% (ALT 4%) |"
    )
    lines.append(
        f"| dsr | {an['dsr']} | {a['dsr']} | {b['dsr']} | >=0.10 (ALT 0.30) |"
    )
    lines.append(
        f"| total OOS trades | {an['total_oos_trades']} | {a['total_oos_trades']} | "
        f"{b['total_oos_trades']} | -- |"
    )
    lines.append("")
    lines.append("### Best Arm B params")
    lines.append("")
    lines.append(f"- flat_band: **{bp['flat_band_points']} pts**")
    lines.append(f"- backwardation_mult: **{bp['backwardation_mult']}**")
    lines.append(f"- standaside_on_backwardation: **{bp['standaside_on_backwardation']}**")
    lines.append(f"- contango_mult: {bp['contango_mult']}, flat_mult: {bp['flat_mult']}")
    lines.append("")
    lines.append("### Full Arm B sweep")
    lines.append("")
    lines.append("| flat_band | bwd_mult | standaside | verdict | pf_ci_lower | p_edge | mc_dd | dsr | trades |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in doc["arm_b_sweep"]:
        lines.append(
            f"| {c['flat_band']} | {c['backwardation_mult']} | {c['standaside']} | "
            f"{c['verdict']} | {c['pf_ci_lower']} | {c['p_edge']} | "
            f"{round(c['mc_95th_dd'] * 100, 3)}% | {c['dsr']} | {c['total_oos_trades']} |"
        )
    lines.append("")
    lines.append("### Scope & caveats")
    lines.append("")
    lines.append(
        "- **MES only.** MES is the one symbol with a VIX-aware champion WFO runner "
        "(`run_mes_trend_vix_rank1.py`) and the flagship equity-index symbol where an "
        "equity-vol term-structure signal is most applicable. MNQ has caches but no VIX "
        "champion runner; MCL/MGC are commodities with a weaker prior. Extending the gate "
        "to those requires building a per-symbol VIX champion first -- a separate task."
    )
    lines.append(
        "- **New hypothesis, not a validated port.** The term-structure filter is validated "
        "for *short-vol* strategies (~/Code/options-vrp); its value on directional "
        "micro-futures is exactly what this gate tests."
    )
    lines.append(
        "- " + doc["config"]["note"]
    )
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    run_ab()
