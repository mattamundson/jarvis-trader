#!/usr/bin/env python
"""
E7-FOLLOWUP: SPY/QQQ debit-vertical options overlay on the CERTIFIED SMA-trend
signals, run through the gate-v2 battery (deep-data standard).

Candidate card: `spy_qqq_vertical_spread_sma_trend` (docs/research/
edge-roadmap-candidates-2026-08-18.cards.jsonl), equal priority with futures
per the 2026-07-31 operating rules.

Design (B6 spec + card parameters_sketch):
  * Signal: the CERTIFIED long-only SMA-trend entries (SPY fast=10/slow=40/
    atr=2.0, QQQ fast=8/slow=40/atr=2.5 — gate-v2 PASS champions) — the same
    `generate_sma_trend_signals` ENTRY_NOW events the share strategy trades.
  * Instrument: debit bull-call vertical spread, 30-delta long leg, 5-strike
    width, 30 DTE tenor (within the 7-30 DTE band), 1 spread per signal.
  * Pricing: Black-Scholes synthetic chain. IV proxy = max(20d realized vol,
    VIX/100 for SPY, 1.10*VIX/100 for QQQ) — NO historical IV surface exists
    in the repo, so this is the documented point-in-time proxy (VIX is the
    market's own SPY IV estimate; QQQ vols run ~10% above SPX).
  * Slippage: half-spread (max $0.05, 1% of premium) + 5bps on each leg,
    entry only; expiry settles at intrinsic (exercise/assignment).
  * Exit: hold to expiry, settle at intrinsic value.
  * Capital: $50K, 1 contract per signal (B6).

Gate: WFO 24mo train / 3mo test / 1mo step; OOS trades = entries inside the
test window; trade-level metrics via `backtest._gate_v2_trade_metrics`
(pf_ci_lower, p_edge, mc_95th_dd, DSR, stationarity, win-rate CI).
Verdict criteria (card "Gate-v2 ALT alignment"): PF>=1.2, >=30 OOS trades,
DD<=7%, DSR>=0.30. House-ALT reference values recorded alongside.

Data: deep 1d caches SPY_/QQQ_2015-01-01_2026-08-17_1d.csv, verified with
`backtest.cache_completeness.inspect_cache_file` FIRST (deep-data standard —
never certify on shallow/holed data). VIX daily cache for the IV proxy.

USAGE (from engine/):
    OPT_SYMBOL=SPY .venv/Scripts/python backtest/run_spy_qqq_options_vertical.py
    OPT_SYMBOL=QQQ .venv/Scripts/python backtest/run_spy_qqq_options_vertical.py
Env overrides: OPT_SYMBOL, OPT_FAST, OPT_SLOW, OPT_ATR, OPT_TENOR_DTE,
OPT_TARGET_DELTA, OPT_WIDTH_STRIKES, OPT_CACHE, GATE_V2_VERDICTS_DIR,
OPT_SMOKE=1 (last 30 months, max 3 windows).

Outputs: <GATE_V2_VERDICTS_DIR>/<SYM>_options_vertical_sma_<f>_<s>_<atr>.json,
one row appended to _journal.csv, trades CSV under engine/data/options_backtests/.

RESEARCH-ONLY: this runner never routes to paper/live (MGC DO_NOT_TRADE; SPY
paper trades on a REJECTED verdict pending S2A).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

engine_root = Path(__file__).resolve().parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest._gate_v2_helpers import classify_wfo_consistency  # noqa: E402
from backtest._gate_v2_trade_metrics import (  # noqa: E402
    trade_level_dsr,
    trade_level_mc_95th_dd,
    trade_level_p_edge,
    trade_level_pf_ci_lower,
    trade_level_stationarity,
    trade_level_win_rate_ci_lower,
)
from backtest.cache_completeness import (  # noqa: E402
    US_MARKET_EARLY_CLOSES,
    US_MARKET_HOLIDAYS,
    inspect_cache_file,
)
from backtest.run_spy_options_baseline import (  # noqa: E402
    bs_delta,
    bs_price,
)
from backtest.screen_cert_pipeline import append_journal, cap_pf  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOL = os.environ.get("OPT_SYMBOL", "SPY").upper()
SYM_PARAMS = {"SPY": (10, 40, 2.0), "QQQ": (8, 40, 2.5)}
FAST = int(os.environ.get("OPT_FAST", SYM_PARAMS.get(SYMBOL, (10, 40, 2.0))[0]))
SLOW = int(os.environ.get("OPT_SLOW", SYM_PARAMS.get(SYMBOL, (10, 40, 2.0))[1]))
ATR_TRAIL_MULT = float(
    os.environ.get("OPT_ATR", SYM_PARAMS.get(SYMBOL, (10, 40, 2.0))[2])
)
TENOR_DTE = int(os.environ.get("OPT_TENOR_DTE", "30"))
TARGET_DELTA = float(os.environ.get("OPT_TARGET_DELTA", "0.30"))
WIDTH_STRIKES = int(os.environ.get("OPT_WIDTH_STRIKES", "5"))
CACHE_OVERRIDE = os.environ.get("OPT_CACHE")
SMOKE = os.environ.get("OPT_SMOKE", "0") == "1"
VERDICTS_DIR = Path(
    os.environ.get("GATE_V2_VERDICTS_DIR")
    or (engine_root / "data" / "gate_v2_verdicts")
)
OPT_OUT_DIR = engine_root / "data" / "options_backtests"

CAPITAL = 50_000.0
RISK_FREE = 0.01
SLIPPAGE_BPS = 5.0
HALF_SPREAD_MIN = 0.05
HALF_SPREAD_PCT = 0.01
STRIKE_STEP = 1.0
CHAIN_RADIUS_STRIKES = 25
QQQ_IV_SCALE = 1.10  # QQQ implied vols structurally ~10% above SPX (VIX)

TRAIN_MONTHS = 24
TEST_MONTHS = 3
STEP_MONTHS = 1

# Card criteria ("Gate-v2 ALT alignment"): PF>=1.2, >=30 OOS trades, DD<=7%,
# DSR>=0.30.
CRITERIA = {
    "min_oos_trades": 30,
    "pf_ci_lower_floor": 1.2,
    "mc_95th_dd_ceiling_frac": 0.07,  # 7%
    "dsr_floor": 0.30,
}

GATE_V2_VERDICT_FAMILY = "options_vertical_sma_trend"


@dataclass
class OptTrade:
    """One completed debit vertical spread trade."""

    entry_ts: pd.Timestamp
    entry_price: float  # underlying at entry
    direction: str  # "BULL"
    long_strike: float
    short_strike: float
    long_fill: float
    short_fill: float
    net_debit: float
    expiry: pd.Timestamp
    exit_price_underlying: float
    pnl: float

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_deep_cache(symbol: str) -> pd.DataFrame:
    """Load the deep 1d cache AFTER the completeness gate. Refuses to proceed
    on a cache the engine's own checker does not certify (deep-data standard)."""
    if CACHE_OVERRIDE:
        cand = Path(CACHE_OVERRIDE)
    else:
        cand = engine_root / "backtest" / "cache" / f"{symbol}_2015-01-01_2026-08-17_1d.csv"
    if not cand.exists():
        raise FileNotFoundError(f"deep cache not found: {cand}")
    rep = inspect_cache_file(
        cand,
        holiday_dates=US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES,
    )
    if not rep["trustworthy"]:
        raise RuntimeError(
            f"REFUSING deep run: {cand.name} fails cache_completeness "
            f"({rep['n_suspicious_gaps']} suspicious gaps). Not certifying on "
            f"holed data."
        )
    df = pd.read_csv(cand)    # Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).
    from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402
    df.attrs["cache_provenance"] = _cp(cand)

    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    ts = pd.to_datetime(df[ts_col])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    print(
        f"[{symbol}] {len(df)} bars | {df.index.min().date()} -> "
        f"{df.index.max().date()} | cache_completeness: trustworthy="
        f"{rep['trustworthy']} gaps={rep['n_suspicious_gaps']}",
        flush=True,
    )
    return df


def load_vix() -> pd.Series:
    path = engine_root / "data" / "vix_daily.csv"
    if not path.exists():
        print("[vix] cache missing — IV proxy will be realized-vol only", flush=True)
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["close"].sort_index()
    print(f"[vix] {len(s)} daily closes | {s.index.min().date()} -> {s.index.max().date()}", flush=True)
    return s


# ---------------------------------------------------------------------------
# Synthetic chain + spread selection (B6 semantics)
# ---------------------------------------------------------------------------

def build_chain(spot: float, iv: float, t_years: float):
    """Strike-grid calls/puts with BS mid prices + deltas."""
    center = int(round(spot))
    strikes = [
        float(k)
        for k in range(
            center - CHAIN_RADIUS_STRIKES, center + CHAIN_RADIUS_STRIKES + 1
        )
    ]
    calls, puts = [], []
    for k in strikes:
        calls.append(
            {
                "strike": k,
                "mid": bs_price(spot, k, t_years, iv, RISK_FREE, "call"),
                "delta": bs_delta(spot, k, t_years, iv, RISK_FREE, "call"),
                "type": "call",
            }
        )
        puts.append(
            {
                "strike": k,
                "mid": bs_price(spot, k, t_years, iv, RISK_FREE, "put"),
                "delta": bs_delta(spot, k, t_years, iv, RISK_FREE, "put"),
                "type": "put",
            }
        )
    return calls, puts


def fill_price(mid: float, side: str) -> float:
    """BUY at mid + half-spread + 5bps; SELL at mid - half-spread - 5bps."""
    half = max(HALF_SPREAD_MIN, HALF_SPREAD_PCT * mid)
    drag = mid * (SLIPPAGE_BPS / 10_000.0)
    if side == "BUY":
        return round(mid + half + drag, 4)
    return round(max(0.0, mid - half - drag), 4)


def select_bull_call_spread(
    calls: list[dict], spot: float
) -> tuple[dict, dict] | None:
    """Long leg = call closest to |delta|=TARGET_DELTA; short leg = WIDTH_STRIKES
    strikes higher (5-wide). Returns (long, short) or None."""
    long_leg = min(calls, key=lambda c: abs(abs(c["delta"]) - TARGET_DELTA))
    short_strike = long_leg["strike"] + WIDTH_STRIKES * STRIKE_STEP
    short_cands = [c for c in calls if abs(c["strike"] - short_strike) < 1e-9]
    if not short_cands:
        return None
    return long_leg, short_cands[0]


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_trades(
    df: pd.DataFrame, vix: pd.Series
) -> tuple[list[OptTrade], list[pd.Timestamp]]:
    """Run certified SMA-trend entries through the vertical-spread overlay.

    Returns (trades, entry_dates). Point-in-time: every input to pricing is
    known at the entry bar (trailing RV, VIX close). Settlement uses the
    underlying close on the last trading day <= expiry (exercise/assignment
    at intrinsic). Trades whose expiry is beyond the cache end are dropped
    (cannot settle) and reported as pending.
    """
    sig = generate_sma_trend_signals(
        df,
        fast=FAST,
        slow=SLOW,
        atr_trail_mult=ATR_TRAIL_MULT,
        rv_annual_factor=252,  # daily bars
    )
    closes = df["close"]
    closes_by_date = closes.groupby(closes.index.normalize()).last()
    vix_series = None
    if not vix.empty:
        from backtest.trend_signals import _daily_date_index

        vix_daily = vix.copy()
        # Align tz conventions before the ffill reindex (pandas >= 3.0 raises on a
        # mixed-tz comparison: tz-aware bar index vs naive daily VIX index).
        vix_daily.index = _daily_date_index(vix_daily.index)
        vix_series = vix_daily.reindex(_daily_date_index(sig.index), method="ffill")
        vix_series.index = sig.index

    trades: list[OptTrade] = []
    pending = 0
    for ts, row in sig.iterrows():
        if row["entry_signal"] != "ENTRY_NOW":
            continue
        spot = float(row["close"])
        t_years = TENOR_DTE / 365.0

        rv_ann = float(row["rv_20_ann_pct"]) if pd.notna(row["rv_20_ann_pct"]) else 0.0
        iv = rv_ann / 100.0
        if vix_series is not None:
            vix_val = vix_series.loc[ts]
            if pd.notna(vix_val):
                vix_iv = float(vix_val) / 100.0
                if SYMBOL == "QQQ":
                    vix_iv *= QQQ_IV_SCALE
                iv = max(iv, vix_iv)

        calls, _puts = build_chain(spot, iv, t_years)
        pick = select_bull_call_spread(calls, spot)
        if pick is None:
            continue
        long_c, short_c = pick
        long_fill = fill_price(long_c["mid"], "BUY")
        short_fill = fill_price(short_c["mid"], "SELL")
        net_debit = long_fill - short_fill

        expiry = ts.normalize() + pd.Timedelta(days=TENOR_DTE)
        settle_rows = closes_by_date[closes_by_date.index <= expiry]
        if settle_rows.empty:
            pending += 1
            continue
        settle_date = settle_rows.index[-1]
        s_exp = float(settle_rows.iloc[-1])
        if settle_date > df.index.max().normalize():
            pending += 1
            continue

        # spread intrinsic at expiry = clamp(S_exp - K_long, 0, width)
        width = short_c["strike"] - long_c["strike"]
        spread_intrinsic = max(0.0, min(s_exp - long_c["strike"], width))
        pnl = spread_intrinsic - net_debit

        trades.append(
            OptTrade(
                entry_ts=ts,
                entry_price=spot,
                direction="BULL",
                long_strike=long_c["strike"],
                short_strike=short_c["strike"],
                long_fill=long_fill,
                short_fill=short_fill,
                net_debit=net_debit,
                expiry=pd.Timestamp(settle_date),
                exit_price_underlying=s_exp,
                pnl=pnl,
            )
        )
    print(
        f"[{SYMBOL}] certified entries -> {len(trades)} settled spreads, "
        f"{pending} pending (expiry beyond cache end)",
        flush=True,
    )
    return trades


# ---------------------------------------------------------------------------
# WFO + gate metrics
# ---------------------------------------------------------------------------

def make_windows(df: pd.DataFrame) -> list[tuple]:
    windows = []
    start = df.index.min()
    end = df.index.max()
    train_start = start
    while True:
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)
        if test_end > end:
            break
        windows.append((train_start, train_end, train_end, test_end))
        train_start += pd.DateOffset(months=STEP_MONTHS)
    return windows


def _window_pf(pnls: list[float]) -> float:
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    if gross_loss == 0:
        return 5.0 if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _window_dd_pct(pnls: list[float]) -> float:
    """Max drawdown (percent of capital) of the cumulative trade-pnl path."""
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return mdd / CAPITAL * 100.0


def _trade_objects(pnls: list[float]) -> list[SimpleNamespace]:
    return [SimpleNamespace(pnl=p) for p in pnls]


def evaluate(trades: list[OptTrade], windows: list[tuple]) -> dict:
    """Bucket trades by entry into OOS test windows; compute gate metrics.

    Attribution is UNIQUE: the 3-month test windows overlap by 2 months (step
    1mo), so each trade is assigned to the FIRST test window containing its
    entry timestamp. Every trade is counted exactly once — the concatenated
    OOS series therefore has no duplicated PnLs (unlike a per-window
    double-count, which would tighten CIs and inflate p_edge/DSR).
    """
    oos_by_window: list[list[OptTrade]] = [[] for _ in windows]
    for t in trades:
        for i, (_tr_s, _tr_e, te_s, te_e) in enumerate(windows):
            if te_s <= t.entry_ts < te_e:
                oos_by_window[i].append(t)
                break
    per_window_trades = [len(w) for w in oos_by_window]
    oos_pfs = [cap_pf(_window_pf([t.pnl for t in w])) for w in oos_by_window]
    oos_dds_pct = [_window_dd_pct([t.pnl for t in w]) for w in oos_by_window]

    total_oos = sum(per_window_trades)
    oos_results = [
        SimpleNamespace(trades=_trade_objects([t.pnl for t in w]))
        for w in oos_by_window
    ]

    metrics: dict = {}
    metrics["total_oos_trades"] = total_oos
    metrics["per_window_trades"] = per_window_trades
    metrics["windows_with_trades"] = sum(1 for n in per_window_trades if n > 0)
    metrics["oos_pfs"] = [round(float(p), 4) for p in oos_pfs]
    metrics["oos_dds_pct"] = [round(float(d), 4) for d in oos_dds_pct]
    metrics["mean_pf"] = round(float(np.mean([p for p in oos_pfs if p is not None])), 4) if any(p is not None for p in oos_pfs) else 0.0
    metrics["median_pf"] = round(float(np.median([p for p in oos_pfs if p is not None])), 4) if any(p is not None for p in oos_pfs) else 0.0
    metrics["wfo_consistency"] = classify_wfo_consistency([p for p in oos_pfs if p is not None])

    # Trade-level battery (single certified combo -> n_trials=1)
    metrics["pf_ci_lower"] = round(trade_level_pf_ci_lower(oos_results), 4)
    metrics["p_edge"] = round(trade_level_p_edge(oos_results), 4)
    metrics["mc_95th_dd"] = round(trade_level_mc_95th_dd(oos_results, CAPITAL), 4)
    metrics["mc_95th_dd_pct"] = round(metrics["mc_95th_dd"] * 100.0, 4)
    metrics["dsr"] = round(trade_level_dsr(oos_results, n_grid_combos=1, initial_capital=CAPITAL), 4)
    metrics["win_rate_ci_lower"] = round(trade_level_win_rate_ci_lower(oos_results), 4)
    st = trade_level_stationarity(oos_results)
    metrics["stationarity_consistent"] = bool(st.get("consistent"))

    all_pnls = [t.pnl for t in trades]
    wins = sum(1 for p in all_pnls if p > 0)
    metrics["win_rate"] = round(wins / len(all_pnls), 4) if all_pnls else 0.0
    metrics["total_pnl_usd"] = round(sum(all_pnls), 2)
    metrics["avg_pnl_usd"] = round(float(np.mean(all_pnls)), 2) if all_pnls else 0.0
    metrics["median_pnl_usd"] = round(float(np.median(all_pnls)), 2) if all_pnls else 0.0
    debits = [t.net_debit for t in trades]
    metrics["avg_debit_usd"] = round(float(np.mean(debits)), 2) if debits else 0.0
    metrics["max_win_usd"] = round(max(all_pnls), 2) if all_pnls else 0.0
    metrics["max_loss_usd"] = round(min(all_pnls), 2) if all_pnls else 0.0
    metrics["capital"] = CAPITAL
    metrics["n_trials_dsr"] = 1
    return metrics


def verdict_from_metrics(m: dict) -> tuple[str, list[str]]:
    reasons = []
    ok_trades = m["total_oos_trades"] >= CRITERIA["min_oos_trades"]
    ok_pf = m["pf_ci_lower"] >= CRITERIA["pf_ci_lower_floor"]
    ok_dd = m["mc_95th_dd"] <= CRITERIA["mc_95th_dd_ceiling_frac"]
    ok_dsr = m["dsr"] >= CRITERIA["dsr_floor"]
    if not ok_trades:
        reasons.append(f"OOS trades {m['total_oos_trades']} < {CRITERIA['min_oos_trades']}")
    if not ok_pf:
        reasons.append(f"pf_ci_lower {m['pf_ci_lower']} < {CRITERIA['pf_ci_lower_floor']}")
    if not ok_dd:
        reasons.append(f"mc_95th_dd {m['mc_95th_dd']:.4f} > {CRITERIA['mc_95th_dd_ceiling_frac']}")
    if not ok_dsr:
        reasons.append(f"dsr {m['dsr']:.4f} < {CRITERIA['dsr_floor']}")
    passed = ok_trades and ok_pf and ok_dd and ok_dsr
    return ("PASS" if passed else "FAIL"), reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    df = load_deep_cache(SYMBOL)
    vix = load_vix()
    if SMOKE:
        start = df.index.max() - pd.DateOffset(months=30)
        df = df.loc[start:]
        print(f"[SMOKE] sliced to last 30 months -> {len(df)} bars", flush=True)

    trades = replay_trades(df, vix)
    windows = make_windows(df)
    if SMOKE:
        windows = windows[:3]
    print(
        f"[{SYMBOL}] windows={len(windows)} (train {TRAIN_MONTHS}mo / test "
        f"{TEST_MONTHS}mo / step {STEP_MONTHS}mo)",
        flush=True,
    )

    metrics = evaluate(trades, windows)
    verdict, reasons = verdict_from_metrics(metrics)
    n_alt = 1 if verdict == "PASS" else 0

    # House-ALT reference (stricter DD ceiling, p_edge floor) for transparency
    house = {
        "pf_ci_lower_floor": 1.10,
        "p_edge_floor": 0.95,
        "mc_95th_dd_ceiling_frac": 0.04,
        "dsr_floor": 0.30,
        "passes_house_alt": bool(
            metrics["pf_ci_lower"] >= 1.10
            and metrics["p_edge"] >= 0.95
            and metrics["mc_95th_dd"] <= 0.04
            and metrics["dsr"] >= 0.30
            and metrics["total_oos_trades"] >= 30
        ),
    }

    out = {
        "symbol": SYMBOL,
        "family": GATE_V2_VERDICT_FAMILY,
        "rank": 0,
        "params": {
            "fast": FAST,
            "slow": SLOW,
            "atr_trail_mult": ATR_TRAIL_MULT,
            "target_delta": TARGET_DELTA,
            "width_strikes": WIDTH_STRIKES,
            "tenor_dte": TENOR_DTE,
            "contracts_per_signal": 1,
            "slippage": "half-spread(max $0.05, 1% mid) + 5bps per leg, entry only",
            "iv_proxy": (
                "max(20d realized vol, VIX/100)"
                if SYMBOL == "SPY"
                else "max(20d realized vol, 1.10*VIX/100)"
            ),
            "exit": "hold to expiry, settle at intrinsic",
        },
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "core_verdict": "FAIL",
        "alt_verdict": verdict,
        "n_core_passed": 0,
        "n_alt_passed": n_alt,
        "wfo_config": {
            "n_windows": len(windows),
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
        },
        "aux_freshness": {},
        "gate_v2": {
            "verdict": verdict,
            "passed_via": "alt" if verdict == "PASS" else None,
            "core_verdict": "FAIL",
            "alt_verdict": verdict,
            "n_core_passed": 0,
            "n_alt_passed": n_alt,
            "reasons": reasons,
            "core_reasons": ["CORE battery not scored (ALT-path options cert)"],
            "alt_reasons": reasons if verdict == "FAIL" else [],
        },
        "criteria": {
            "min_oos_trades": CRITERIA["min_oos_trades"],
            "pf_ci_lower_floor": CRITERIA["pf_ci_lower_floor"],
            "mc_95th_dd_ceiling_frac": CRITERIA["mc_95th_dd_ceiling_frac"],
            "dsr_floor": CRITERIA["dsr_floor"],
            "house_alt_reference": house,
        },
        "gate_v2_metrics": metrics,
        "data_quality": {
            "cache": f"backtest/cache/{SYMBOL}_2015-01-01_2026-08-17_1d.csv",
            "cache_completeness": {
                "trustworthy": True,
                "n_bars": len(df),
                "span": [str(df.index.min().date()), str(df.index.max().date())],
                "checked_via": "backtest.cache_completeness.inspect_cache_file",
                "note": "US_MARKET_HOLIDAYS extended back to 2015 (2026-08-18 "
                        "E7-FOLLOWUP); independent NYSE-closure cross-check showed "
                        "zero missing non-holiday trading days",
            },
            "n_trades_total": len(trades),
            "n_trades_oos": metrics["total_oos_trades"],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lineage": (
            "E7 t_b9f01895 -> spy_qqq_vertical_spread_sma_trend card -> "
            "run_spy_qqq_options_vertical.py (deep 1d caches, gate-v2 ALT "
            "battery). RESEARCH-ONLY; no paper/live routing."
        ),
    }

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = VERDICTS_DIR / f"{SYMBOL}_options_vertical_sma_{FAST}_{SLOW}_{ATR_TRAIL_MULT}.json"
    # Record the provenance carried on the frame (see loader).
    from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402
    out = _ip(out, df=df)
    out_file.write_text(json.dumps(out, indent=2, allow_nan=False))
    append_journal(VERDICTS_DIR, out, source_file=out_file.name)

    OPT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    trades_csv = (
        OPT_OUT_DIR / f"{SYMBOL}_vertical_sma_{FAST}_{SLOW}_{ATR_TRAIL_MULT}_trades.csv"
    )
    pd.DataFrame(
        [
            {
                "entry_ts": t.entry_ts.isoformat(),
                "entry_price": round(t.entry_price, 2),
                "direction": t.direction,
                "long_strike": t.long_strike,
                "short_strike": t.short_strike,
                "net_debit": round(t.net_debit, 4),
                "expiry": t.expiry.date().isoformat(),
                "underlying_at_expiry": round(t.exit_price_underlying, 2),
                "pnl": round(t.pnl, 4),
            }
            for t in trades
        ]
    ).to_csv(trades_csv, index=False)

    print(f"\n=== {SYMBOL} options vertical ({FAST},{SLOW},{ATR_TRAIL_MULT}) ===")
    print(f"  trades={len(trades)} oos={metrics['total_oos_trades']} "
          f"windows_with_trades={metrics['windows_with_trades']}")
    print(f"  pf_ci_lower={metrics['pf_ci_lower']:.4f} p_edge={metrics['p_edge']:.4f} "
          f"dsr={metrics['dsr']:.4f} mc_95th_dd={metrics['mc_95th_dd_pct']:.2f}%")
    print(f"  win_rate={metrics['win_rate']:.4f} total_pnl=${metrics['total_pnl_usd']:,.2f}")
    print(f"  verdict={verdict} {'| reasons: ' + '; '.join(reasons) if reasons else ''}")
    print(f"  Wrote -> {out_file}")
    print(f"  Trades -> {trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
