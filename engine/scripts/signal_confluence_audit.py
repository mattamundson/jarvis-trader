"""
Signal Confluence Audit — JARVIS TRADER.

A single orchestrator that fires three independent reads and emits ONE verdict
on whether the auction/profile family (the bottom CoreyTscorev2 + Saty ATR
context on the ToS chart) carries OOS edge beyond the validated SMA-trend
champion on MES:

  1. corey-IC   — live Information Coefficient of the Corey auction analyst,
                  pulled from GET /analytics/calibration (the agent's directional
                  edge vs realized P&L). Falls back to offline ICWeightedEnsemble
                  when the engine is unreachable.
  2. trend      — SMA-trend champion (the validated MES baseline), grid-searched
                  on the train slice, applied OOS. This is the bar to beat.
  3. auction    — composite (STC+ORB+VWAP) and a TPO-score threshold arm, the
                  backtested representation of the chart's profile/value read.

This is a SINGLE-SPLIT DIRECTIONAL SCREEN, not a verdict. It does NOT feed any
paper-promotion or go/no-go gate, and it must NEVER be cited as evidence that a
strategy lacks edge. Two structural reasons it cannot refute a strategy:

  - It uses ONE fixed train/test split. For a low-frequency strategy (the MES
    trend champion fires ~1 trade/month → ~16 OOS trades across its whole
    validation), a single OOS slice lands in one regime and a profit factor
    computed on ~10 trades is noise. The validated champion earned its p_edge
    via a ROLLING walk-forward (many windows), not a single hold-out.
  - It grid-searches several arms (max-of-N is biased up; ml-pitfalls-defense.md
    #3/#4). No Deflated-Sharpe / permutation correction is applied here.

For promotion-grade evidence use scripts/validate_strategy.py (rolling
walk-forward + gate v2: p_edge / DSR / MC-drawdown / cost survival). A "winner"
here is at most a candidate to feed into that pipeline.

If an arm produces few or zero OOS trades, that is a DIAGNOSTIC RESULT about the
arm's gating, not proof of no edge — run --diagnose to see the entry funnel
(regime / ADX / signal-cross counts) before drawing any conclusion.

Usage (from engine/):
  .venv/Scripts/python -m scripts.signal_confluence_audit
  .venv/Scripts/python -m scripts.signal_confluence_audit --json out.json
  .venv/Scripts/python -m scripts.signal_confluence_audit --diagnose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

# ── Shared config (mirrors scripts/strategy_comparison.py so arms are comparable)
DEFAULT_ENGINE_URL = "http://localhost:8010"
SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 10_000.0
INTERVAL = "1h"
FULL_START = "2024-06-01"
TRAIN_END = "2025-06-01"
TEST_END = "2026-03-27"

# Minimum OOS trades before an arm's PF is trusted enough to rank.
MIN_OOS_TRADES = 10
# Margin an auction arm must clear over the trend baseline's OOS PF to be called
# an edge candidate (10% — below this is noise given the grid search).
EDGE_MARGIN = 1.10

_BT_KWARGS = {
    "initial_capital": CAPITAL,
    "trailing_stop": True,
    "t1_exit_pct": 1.0,
    "t2_exit_pct": 0.0,
    "strict_trailing": True,
    "eod_close": False,
    "use_targets": False,
    "fixed_contracts": 1,
    "max_drawdown": 0.99,
    "max_daily_loss": 0.99,
}

# TPO arm: tpo_score crossing these thresholds opens a trade; ATR-scaled stop.
TPO_ENTER_GRID = (0.33, 0.50, 0.66)
TPO_STOP_GRID = (1.0, 1.5, 2.0)
TPO_ATR_PERIOD = 14

# Saty arm: the chart's Calls>/Puts< trigger-break levels (GO continuation mode).
SATY_TARGET_GRID = (1.0, 1.5, 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. corey-IC (live, with offline fallback)
# ─────────────────────────────────────────────────────────────────────────────


def _read_api_key() -> str | None:
    """Read API_KEY from env, else parse engine/.env at use time (it rotates)."""
    key = os.environ.get("API_KEY")
    if key:
        return key
    env_file = ENGINE_DIR / ".env"
    if not env_file.exists():
        return None
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        return None
    return None


def fetch_corey_ic(engine_url: str = DEFAULT_ENGINE_URL, timeout: float = 8.0) -> dict:
    """Return the Corey auction analyst's live calibration entry.

    Tries GET /analytics/calibration first; on any failure, computes IC offline
    from the trade_outcomes table via ICWeightedEnsemble. Always returns a dict
    with at least {available, source}.
    """
    req = urllib.request.Request(f"{engine_url}/analytics/calibration", method="GET")
    api_key = _read_api_key()
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        entry = (data.get("per_agent") or {}).get("corey", {})
        return {
            "available": True,
            "source": "engine:/analytics/calibration",
            "ic_score": entry.get("ic_score"),
            "sample_count": entry.get("sample_count"),
            "ready": entry.get("ready"),
            "min_trades_threshold": data.get("min_trades_threshold"),
            "window_days": data.get("window_days"),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        logger.warning("calibration endpoint unreachable (%s) — trying offline IC", exc)
        return _fetch_corey_ic_offline()


def _fetch_corey_ic_offline() -> dict:
    """Compute corey IC directly from the analytics DB (engine down path)."""
    try:
        from analytics.ic_ensemble import MIN_TRADES_FOR_IC, ICWeightedEnsemble

        ic = ICWeightedEnsemble(agents=["corey"])
        score = ic.compute_ic("corey")
        return {
            "available": True,
            "source": "offline:ICWeightedEnsemble",
            "ic_score": round(float(score), 6),
            "sample_count": None,
            "ready": None,
            "min_trades_threshold": int(MIN_TRADES_FOR_IC),
            "window_days": None,
        }
    except Exception as exc:  # noqa: BLE001 — diagnostic, never abort the audit
        logger.warning("offline IC unavailable: %s", exc)
        return {"available": False, "source": "none", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 2 & 3. Backtest arms (lazy heavy imports — keeps pure functions importable)
# ─────────────────────────────────────────────────────────────────────────────


def _load_mes(test_end: str = TEST_END):
    """Load MES OHLCV; returns DataFrame or None when data/cache is unavailable."""
    try:
        from backtest import BacktestDataLoader

        df = BacktestDataLoader().load(SYMBOL, FULL_START, test_end, interval=INTERVAL)
        if df is None or len(df) == 0:
            return None
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("MES data load failed: %s", exc)
        return None


def _run_bt(df_sig, atr_trail: float) -> dict:
    from backtest import Backtester

    r = Backtester(**_BT_KWARGS, trailing_atr_mult=atr_trail).run(df_sig, SYMBOL, MULTIPLIER)
    return {
        "pf": r.profit_factor,
        "sharpe": r.sharpe_ratio,
        "n_trades": r.total_trades,
        "win_rate": r.win_rate,
        "max_dd": r.max_drawdown_pct,
        "total_return_pct": r.total_return_pct,
    }


def _walk(name: str, df_full, grid_fn, apply_fn, test_end: str = TEST_END) -> dict:
    """Grid-search on train, apply champion OOS + full period, package metrics."""
    import pandas as pd  # noqa: F401 — index comparison below needs pandas types

    train = df_full[(df_full.index >= FULL_START) & (df_full.index < TRAIN_END)].copy()
    test = df_full[(df_full.index >= TRAIN_END) & (df_full.index < test_end)].copy()
    if len(train) == 0 or len(test) == 0:
        return {"arm": name, "status": "no_data"}

    best_params, train_m = grid_fn(train)
    if best_params is None:
        return {"arm": name, "status": "no_combos"}
    atr_trail = best_params.get("atr_trail", 2.0)
    try:
        test_m = _run_bt(apply_fn(test.copy(), best_params), atr_trail)
        full_m = _run_bt(apply_fn(df_full.copy(), best_params), atr_trail)
    except Exception as exc:  # noqa: BLE001
        return {"arm": name, "status": "error", "error": str(exc), "champion_params": best_params}

    wfe = test_m["pf"] / train_m["pf"] if train_m["pf"] > 0 else 0.0
    return {
        "arm": name,
        "status": "ok",
        "champion_params": best_params,
        "train": {k: round(v, 4) for k, v in train_m.items()},
        "test": {k: round(v, 4) for k, v in test_m.items()},
        "full_period": {k: round(v, 4) for k, v in full_m.items()},
        "wfe": round(wfe, 4),
        "oos_pf": round(test_m["pf"], 4),
        "oos_sharpe": round(test_m["sharpe"], 4),
        "oos_trades": int(test_m["n_trades"]),
    }


def _grid_trend(df_train):
    from itertools import product

    from backtest.trend_signals import generate_sma_trend_signals

    best = (-1.0, None, None)
    for fast, slow, trail in product((40, 50, 60), (175, 200, 225), (1.5, 2.0, 2.5)):
        if fast >= slow:
            continue
        try:
            m = _run_bt(generate_sma_trend_signals(df_train.copy(), fast=fast, slow=slow, atr_trail_mult=trail), trail)
        except Exception:  # noqa: BLE001
            continue
        if m["n_trades"] >= 5 and m["pf"] > best[0]:
            best = (m["pf"], {"fast": fast, "slow": slow, "atr_trail": trail}, m)
    return best[1], best[2]


def _apply_trend(df, params):
    from backtest.trend_signals import generate_sma_trend_signals

    return generate_sma_trend_signals(df, fast=params["fast"], slow=params["slow"], atr_trail_mult=params["atr_trail"])


def _grid_composite(df_train):
    """Composite runs at canonical params (Tier-3 to tune) — no grid search."""
    params = {"atr_trail": 2.0}
    try:
        m = _run_bt(_apply_composite(df_train.copy(), params), 2.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("composite train run failed: %s", exc)
        return None, None
    if m["n_trades"] < 5:
        return None, None
    return params, m


def _apply_composite(df, params):
    from backtest.composite_signals import generate_composite_signals

    return generate_composite_signals(df, symbol=SYMBOL)


def _tpo_contract(df, enter: float, stop_mult: float):
    """Convert tpo_score into a Backtester-contract frame.

    Entry: tpo_score crossing above +enter → long, below -enter → short.
    Stop:  stop_mult * ATR(14) from close. Targets set wide; trailing governs.
    """
    import numpy as np

    from backtest.tpo_profile import compute_tpo_profile
    from backtest.tpo_score import compute_tpo_score

    out = compute_tpo_score(compute_tpo_profile(df.copy()))
    score = out["tpo_score"].to_numpy()
    prev = np.concatenate([[0.0], score[:-1]])
    long_x = (score >= enter) & (prev < enter)
    short_x = (score <= -enter) & (prev > -enter)

    tr = (out["high"] - out["low"]).abs()
    atr = tr.rolling(TPO_ATR_PERIOD, min_periods=1).mean().to_numpy()
    close = out["close"].to_numpy()

    out["entry_signal"] = np.where(long_x | short_x, "ENTRY_NOW", "NO_TRADE")
    out["bias"] = np.where(long_x, "BULLISH", np.where(short_x, "BEARISH", "NEUTRAL"))
    out["stop_level"] = np.where(long_x, close - stop_mult * atr, close + stop_mult * atr)
    out["target_1"] = np.where(long_x, close + 2 * stop_mult * atr, close - 2 * stop_mult * atr)
    out["target_2"] = out["target_1"]
    out["target_3"] = out["target_1"]
    if "regime" not in out.columns:
        out["regime"] = "NEUTRAL"
    return out


def _grid_tpo(df_train):
    from itertools import product

    best = (-1.0, None, None)
    for enter, stop_mult in product(TPO_ENTER_GRID, TPO_STOP_GRID):
        try:
            m = _run_bt(_tpo_contract(df_train.copy(), enter, stop_mult), stop_mult)
        except Exception:  # noqa: BLE001
            continue
        if m["n_trades"] >= 5 and m["pf"] > best[0]:
            best = (m["pf"], {"enter": enter, "stop_mult": stop_mult, "atr_trail": stop_mult}, m)
    return best[1], best[2]


def _apply_tpo(df, params):
    return _tpo_contract(df, params["enter"], params["stop_mult"])


def _grid_saty(df_train):
    from backtest.saty_atr_signals import generate_saty_atr_signals

    best = (-1.0, None, None)
    for target_ratio in SATY_TARGET_GRID:
        try:
            sig = generate_saty_atr_signals(df_train.copy(), mode="go", target_ratio=target_ratio)
            m = _run_bt(sig, 2.0)
        except Exception:  # noqa: BLE001
            continue
        if m["n_trades"] >= 5 and m["pf"] > best[0]:
            best = (m["pf"], {"target_ratio": target_ratio, "atr_trail": 2.0}, m)
    return best[1], best[2]


def _apply_saty(df, params):
    from backtest.saty_atr_signals import generate_saty_atr_signals

    return generate_saty_atr_signals(df, mode="go", target_ratio=params["target_ratio"])


def _apply_atrtrail(df, params):
    """ATR trailing-stop FLIP (the TOS ATRTrailingStopLE/SE rule) signal frame."""
    from backtest.atr_trail_bounce_signals import generate_atr_trail_flip_signals

    return generate_atr_trail_flip_signals(df, atr_period=5, factor=params["factor"])


def _grid_atrtrail(df_train):
    """Grid the ATR-trail flip over the trailing-stop factor (TOS default 3.5)."""
    best = (-1.0, None, None)
    for factor in (3.0, 3.5, 4.0):
        try:
            m = _run_bt(_apply_atrtrail(df_train.copy(), {"factor": factor}), 2.0)
        except Exception:  # noqa: BLE001
            continue
        if m["n_trades"] >= 5 and m["pf"] > best[0]:
            best = (m["pf"], {"factor": factor, "atr_trail": 2.0}, m)
    return best[1], best[2]


ARMS = {
    "trend": (_grid_trend, _apply_trend),
    "composite": (_grid_composite, _apply_composite),
    "tpo": (_grid_tpo, _apply_tpo),
    "saty": (_grid_saty, _apply_saty),
    "atrtrail": (_grid_atrtrail, _apply_atrtrail),
}

# Representative (mid-grid) params used ONLY by --diagnose to count raw entry
# signals per arm. Not a champion selection — just a single sane point so the
# entry funnel is visible without a grid search. Keys must match each apply_fn.
DIAGNOSE_PARAMS = {
    "trend": {"fast": 60, "slow": 200, "atr_trail": 2.0},
    "composite": {"atr_trail": 2.0},
    "tpo": {"enter": 0.33, "stop_mult": 1.5, "atr_trail": 1.5},
    "saty": {"target_ratio": 1.5, "atr_trail": 2.0},
    "atrtrail": {"factor": 3.5},
}


def run_backtest_arms(df_full, test_end: str = TEST_END) -> list[dict]:
    """Run every arm against the loaded frame. Pure orchestration over _walk."""
    arms = []
    for name, (grid_fn, apply_fn) in ARMS.items():
        logger.info("running arm: %s", name)
        arms.append(_walk(name, df_full, grid_fn, apply_fn, test_end=test_end))
    return arms


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic — raw entry funnel (why an arm goes silent), no min-trade gate
# ─────────────────────────────────────────────────────────────────────────────


def _entry_count(df_sig) -> int:
    """Count ENTRY_NOW rows in a signal frame (0 if column/frame missing)."""
    if df_sig is None or "entry_signal" not in getattr(df_sig, "columns", []):
        return 0
    return int((df_sig["entry_signal"] == "ENTRY_NOW").sum())


def _composite_funnel(df_sig) -> dict:
    """Expose the composite entry gates so a 0-trade slice is explainable.

    Composite blocks entries in VOLATILE regime and when ADX < 25, and gates on
    an STC cross. If a slice produces no trades, these counts say which gate shut
    it off (a gating result, NOT proof of no edge).
    """
    out: dict = {}
    if df_sig is None:
        return out
    cols = getattr(df_sig, "columns", [])
    if "regime_type" in cols:
        out["regime"] = {str(k): int(v) for k, v in df_sig["regime_type"].value_counts().items()}
    if "adx" in cols:
        adx = df_sig["adx"].dropna()
        out["adx_ge_25_pct"] = round(float((adx >= 25).mean()), 3) if len(adx) else None
    for col in ("stc_cross_up", "stc_cross_down"):
        if col in cols:
            out[col] = int(df_sig[col].astype(bool).sum())
    return out


def diagnose_arms(df_full, test_end: str = TEST_END) -> list[dict]:
    """Apply each arm at a fixed param point and count raw entries per slice.

    Reveals silent-zero arms BEFORE the min-trade gate that the main audit
    swallows into no_combos/no_data. For composite, also reports the gate funnel.
    """
    train = df_full[(df_full.index >= FULL_START) & (df_full.index < TRAIN_END)].copy()
    test = df_full[(df_full.index >= TRAIN_END) & (df_full.index < test_end)].copy()
    rows: list[dict] = []
    for name, (_grid_fn, apply_fn) in ARMS.items():
        params = DIAGNOSE_PARAMS[name]
        row: dict = {"arm": name, "train_bars": len(train), "test_bars": len(test)}
        for slc, frame in (("train", train), ("test", test)):
            if len(frame) == 0:
                row[f"{slc}_entries"] = 0
                continue
            try:
                sig = apply_fn(frame.copy(), params)
                row[f"{slc}_entries"] = _entry_count(sig)
                if name == "composite":
                    row[f"{slc}_funnel"] = _composite_funnel(sig)
            except Exception as exc:  # noqa: BLE001 — diagnostic, never abort
                row[f"{slc}_entries"] = None
                row[f"{slc}_error"] = str(exc)
        rows.append(row)
    return rows


def format_diagnose(rows: list[dict]) -> str:
    """Render the entry-funnel diagnostic as a human-readable block."""
    lines = [
        "=" * 68,
        "SIGNAL CONFLUENCE — ENTRY FUNNEL DIAGNOSTIC (raw, pre-gate)",
        "=" * 68,
        "Counts raw ENTRY_NOW signals per arm on train vs OOS at a fixed param",
        "point. A 0 here means the arm's GATING shut it off — not proof of no edge.",
        "",
        f"  {'arm':<12}{'train_entries':>15}{'oos_entries':>13}",
    ]
    for r in rows:
        te = r.get("train_entries")
        oe = r.get("test_entries")
        lines.append(f"  {r['arm']:<12}{str(te):>15}{str(oe):>13}")
        if r.get("train_error") or r.get("test_error"):
            lines.append(f"      error: {r.get('train_error') or r.get('test_error')}")
        for slc in ("train", "test"):
            funnel = r.get(f"{slc}_funnel")
            if funnel:
                lines.append(f"      {slc} funnel: {funnel}")
    lines.append("=" * 68)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Verdict (PURE — unit-tested, no data/engine needed)
# ─────────────────────────────────────────────────────────────────────────────


def rank_arms(arms: list[dict], min_trades: int = MIN_OOS_TRADES) -> list[dict]:
    """Return ok arms with enough OOS trades, sorted by OOS PF (desc), rank added."""
    eligible = [
        a for a in arms
        if a.get("status") == "ok" and int(a.get("oos_trades", 0)) >= min_trades
    ]
    ranked = sorted(eligible, key=lambda a: float(a.get("oos_pf", 0.0)), reverse=True)
    for i, a in enumerate(ranked, start=1):
        a["rank"] = i
    return ranked


def build_verdict(
    arms: list[dict],
    corey_ic: dict,
    baseline: str = "trend",
    edge_margin: float = EDGE_MARGIN,
    min_trades: int = MIN_OOS_TRADES,
) -> dict:
    """Combine corey-IC + ranked backtest arms into a single labeled verdict."""
    ranked = rank_arms(arms, min_trades=min_trades)
    base = next((a for a in arms if a.get("arm") == baseline and a.get("status") == "ok"), None)
    base_pf = float(base["oos_pf"]) if base else None

    best = ranked[0] if ranked else None
    ic_score = corey_ic.get("ic_score")
    ic_positive = isinstance(ic_score, (int, float)) and ic_score > 0

    if not ranked:
        label = "INSUFFICIENT_SAMPLE"
        rationale = f"No arm cleared {min_trades} OOS trades — nothing to rank."
    elif best["arm"] == baseline or base_pf is None:
        label = "TREND_DOMINANT"
        rationale = "Trend baseline is the top OOS arm; auction arms add no standalone edge."
    elif float(best["oos_pf"]) > base_pf * edge_margin and ic_positive:
        label = "AUCTION_EDGE_CANDIDATE"
        rationale = (
            f"{best['arm']} OOS PF {best['oos_pf']} clears trend {base_pf} by >{int((edge_margin - 1) * 100)}% "
            f"AND corey IC {ic_score} > 0 — candidate for a sealed walk-forward, not a green light."
        )
    elif float(best["oos_pf"]) > base_pf * edge_margin:
        label = "AUCTION_EDGE_UNCONFIRMED"
        rationale = (
            f"{best['arm']} beats trend on OOS PF but corey IC is {ic_score} (not > 0) — "
            "backtest edge without live agent confirmation. Treat as fragile."
        )
    else:
        label = "TREND_DOMINANT"
        rationale = f"No auction arm beats trend ({base_pf}) by the {edge_margin}x margin."

    # +SMA grid (27) + ATR-trail factor grid (3)
    n_combos = len(TPO_ENTER_GRID) * len(TPO_STOP_GRID) + len(SATY_TARGET_GRID) + 27 + 3
    caveats = [
        "SCREEN, NOT A VERDICT — single fixed train/test split. NEVER cite this as evidence a "
        "strategy lacks edge. For promotion-grade evidence use scripts/validate_strategy.py "
        "(rolling walk-forward + gate v2: p_edge / DSR / MC-DD / cost survival).",
        "Low-frequency caveat: the MES trend champion fires ~1 trade/month; a single OOS slice "
        "yields ~10 trades, so any PF here is noise-dominated. Rank order is indicative only.",
        "An arm with few/zero OOS trades is a GATING result, not no-edge — run --diagnose to see "
        "the entry funnel (regime / ADX / signal-cross counts) before concluding anything.",
        "DIAGNOSTIC — does not feed any paper-promotion or go/no-go gate (ml-pitfalls-defense.md).",
        f"Multiple testing: {len(ARMS)} arms grid-searched (~{n_combos}+ combos); max PF is biased up. "
        "No Deflated Sharpe / permutation test applied — required before paper promotion.",
        "Costs: arms use the shared Backtester cost model; confirm commission is deducted before quoting PF.",
        "corey IC measures the auction *analyst* (commentary + bot proximity), not the raw TPO study.",
    ]
    return {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "verdict": label,
        "rationale": rationale,
        "corey_ic": corey_ic,
        "baseline": baseline,
        "baseline_oos_pf": base_pf,
        "best_arm": best["arm"] if best else None,
        "ranked": [
            {"rank": a["rank"], "arm": a["arm"], "oos_pf": a["oos_pf"],
             "oos_sharpe": a.get("oos_sharpe"), "oos_trades": a["oos_trades"], "wfe": a.get("wfe")}
            for a in ranked
        ],
        "arms_raw": arms,
        "caveats": caveats,
    }


def format_report(verdict: dict) -> str:
    """Render the verdict as a human-readable block."""
    lines = [
        "=" * 68,
        f"SIGNAL CONFLUENCE AUDIT — {verdict['symbol']} {verdict['interval']}",
        "=" * 68,
        f"VERDICT: {verdict['verdict']}",
        f"  {verdict['rationale']}",
        "",
    ]
    ic = verdict["corey_ic"]
    if ic.get("available"):
        lines.append(
            f"corey-IC: {ic.get('ic_score')} "
            f"(n={ic.get('sample_count')}, ready={ic.get('ready')}, src={ic.get('source')})"
        )
    else:
        lines.append(f"corey-IC: unavailable ({ic.get('error', 'no source')})")
    lines.append("")
    lines.append(f"Backtest arms (baseline=trend, OOS PF={verdict['baseline_oos_pf']}):")
    if verdict["ranked"]:
        lines.append(f"  {'rank':<5}{'arm':<12}{'OOS_PF':>9}{'Sharpe':>9}{'trades':>8}{'WFE':>8}")
        for a in verdict["ranked"]:
            lines.append(
                f"  {a['rank']:<5}{a['arm']:<12}{a['oos_pf']:>9}{str(a['oos_sharpe']):>9}"
                f"{a['oos_trades']:>8}{str(a['wfe']):>8}"
            )
    else:
        lines.append("  (no arm met the minimum OOS trade count)")
    skipped = [a for a in verdict["arms_raw"] if a.get("status") != "ok"]
    if skipped:
        lines.append("")
        lines.append("Skipped arms:")
        for a in skipped:
            lines.append(f"  {a['arm']}: {a['status']}{' — ' + a['error'] if a.get('error') else ''}")
    lines.append("")
    lines.append("Caveats:")
    for c in verdict["caveats"]:
        lines.append(f"  - {c}")
    lines.append("=" * 68)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal Confluence Audit — JARVIS TRADER")
    parser.add_argument("--engine-url", default=DEFAULT_ENGINE_URL)
    parser.add_argument("--json", help="Write the full verdict JSON to this path")
    parser.add_argument("--skip-backtest", action="store_true", help="corey-IC only (no data needed)")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print per-arm raw entry funnel (train vs OOS, pre-gate) and exit. "
        "Reveals silent-zero arms the main audit hides behind no_combos/no_data.",
    )
    parser.add_argument(
        "--test-end",
        default=TEST_END,
        help=(
            f"OOS window end date (YYYY-MM-DD). Default {TEST_END} mirrors "
            "strategy_comparison.py for an apples-to-apples trend comparison; "
            "extend it to include more recent data."
        ),
    )
    args = parser.parse_args()

    window = {"full_start": FULL_START, "train_end": TRAIN_END, "test_end": args.test_end}

    # --diagnose: entry-funnel only. Needs data; refuses to pretend on no data.
    if args.diagnose:
        df = _load_mes(test_end=args.test_end)
        if df is None:
            logger.error(
                "No MES data available (cache empty / symbol blocklisted / network down) — "
                "cannot diagnose. Populate the IBKR-sourced backtest cache and retry."
            )
            return 2
        print(format_diagnose(diagnose_arms(df, test_end=args.test_end)))
        return 0

    corey_ic = fetch_corey_ic(args.engine_url)

    arms: list[dict] = []
    if not args.skip_backtest:
        df = _load_mes(test_end=args.test_end)
        if df is None:
            # Refuse to emit a verdict on no data — a silent no_data verdict reads
            # as "tested and found nothing" when nothing was tested. Abort loudly.
            logger.error(
                "No MES data available (cache empty / symbol blocklisted / network down). "
                "Aborting — refusing to emit a confluence verdict on zero data."
            )
            abort = {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "verdict": "NO_DATA_ABORT",
                "rationale": (
                    "BacktestDataLoader returned no MES bars (empty cache / POLYGON_FUTURES_BLOCKLIST "
                    "/ no network). No arm was run; this is NOT a no-edge result."
                ),
                "corey_ic": corey_ic,
                "window": window,
            }
            if args.json:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps(abort, indent=2, default=str))
                logger.info("NO_DATA_ABORT JSON written to %s", args.json)
            return 2
        arms = run_backtest_arms(df, test_end=args.test_end)

    verdict = build_verdict(arms, corey_ic)
    verdict["window"] = window
    print(format_report(verdict))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(verdict, indent=2, default=str))
        logger.info("verdict JSON written to %s", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
