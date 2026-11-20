"""Causal weekly-VWAP acceptance study for MES 5-minute OHLCV.

Every feature at a decision time uses only completed bars before that time. The
"cumulative delta" feature is explicitly an OHLCV close-location-volume proxy;
true bid/ask delta is unavailable in the cache and is never claimed.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, time
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backtest.research.session_data import (
    MES_MULTIPLIER,
    ROUND_TRIP_FEES,
    TICK_SIZE,
    add_session_columns,
    paired_block_bootstrap_stats,
    strategy_metrics,
)

CLASSES = ("continuation", "rotation", "failure")
FEATURES = ("time", "volume", "developing_vpoc", "developing_tpo_poc", "clv_delta_proxy")
DECISION_TIMES = (time(10, 30), time(11, 30), time(12, 30))
MIN_TRAIN = 60
MIN_STATE_TRAIN = 30
DIRICHLET_ALPHA = 1.0


@dataclass(frozen=True)
class AcceptanceRecord:
    signal_date: str
    decision_time_ct: str
    week_key: str
    decision_timestamp: str
    decision_price: float
    weekly_vwap: float
    session_close: float
    session_low: float
    next_close: float
    next_low: float
    realized: str
    baseline_above_vwap: bool
    time_acceptance: bool
    volume_acceptance: bool
    developing_vpoc_acceptance: bool
    developing_tpo_poc_acceptance: bool
    clv_delta_proxy_acceptance: bool
    volume_fraction_above_vwap: float
    developing_vpoc: float
    developing_tpo_poc: float
    clv_delta_proxy: float


def _time_before(ts: pd.Timestamp, cutoff: time) -> bool:
    return ts.time() < cutoff


def add_developing_weekly_vwap(df: pd.DataFrame) -> pd.DataFrame:
    tagged = add_session_columns(df)
    typical = (tagged["high"] + tagged["low"] + tagged["close"]) / 3.0
    pv = typical * tagged["volume"]
    tagged["weekly_cum_pv"] = pv.groupby(tagged["week_key"]).cumsum()
    tagged["weekly_cum_volume"] = tagged["volume"].groupby(tagged["week_key"]).cumsum()
    tagged["weekly_vwap"] = tagged["weekly_cum_pv"] / tagged["weekly_cum_volume"].replace(0, np.nan)
    tagged["weekly_vwap"] = tagged.groupby("week_key")["weekly_vwap"].ffill()
    return tagged


def _volume_poc(bars: pd.DataFrame, tick_size: float = TICK_SIZE) -> float:
    volume_at_price: defaultdict[float, float] = defaultdict(float)
    for _, bar in bars.iterrows():
        low_tick = math.floor(float(bar["low"]) / tick_size)
        high_tick = math.ceil(float(bar["high"]) / tick_size)
        ticks = list(range(low_tick, high_tick + 1))
        if not ticks:
            continue
        share = float(bar["volume"]) / len(ticks)
        for tick in ticks:
            volume_at_price[round(tick * tick_size, 10)] += share
    if not volume_at_price:
        return float("nan")
    max_volume = max(volume_at_price.values())
    candidates = [price for price, volume in volume_at_price.items() if abs(volume - max_volume) < 1e-9]
    midpoint = (float(bars["high"].max()) + float(bars["low"].min())) / 2.0
    return min(candidates, key=lambda price: (abs(price - midpoint), price))


def _tpo_poc(bars: pd.DataFrame, decision_time: time, tick_size: float = TICK_SIZE) -> float:
    """POC from completed 30-minute periods only."""
    if bars.empty:
        return float("nan")
    local = pd.DatetimeIndex(bars["local_ct"])
    minute_from_open = (local.hour * 60 + local.minute) - (8 * 60 + 30)
    period_id = minute_from_open // 30
    work = bars.copy()
    work["period_id"] = period_id
    counts: Counter[float] = Counter()
    for _, period in work.groupby("period_id"):
        period_start = pd.Timestamp(period["local_ct"].iloc[0])
        if (period_start + pd.Timedelta(minutes=30)).time() > decision_time:
            continue
        low_tick = math.floor(float(period["low"].min()) / tick_size)
        high_tick = math.ceil(float(period["high"].max()) / tick_size)
        for tick in range(low_tick, high_tick + 1):
            counts[round(tick * tick_size, 10)] += 1
    if not counts:
        return float("nan")
    max_count = max(counts.values())
    candidates = [price for price, count in counts.items() if count == max_count]
    midpoint = (float(bars["high"].max()) + float(bars["low"].min())) / 2.0
    return min(candidates, key=lambda price: (abs(price - midpoint), price))


def label_partition(next_close: float, next_low: float, signal_close: float, signal_low: float) -> str:
    if next_close > signal_close:
        return "continuation"
    if next_low < signal_low:
        return "failure"
    return "rotation"


def build_acceptance_records(df: pd.DataFrame) -> list[AcceptanceRecord]:
    tagged = add_developing_weekly_vwap(df)
    rth = tagged[tagged["is_rth"]]
    session_groups = [(d, g) for d, g in rth.groupby("trade_date", sort=True) if len(g) >= 60]
    records: list[AcceptanceRecord] = []
    for i in range(len(session_groups) - 1):
        signal_date, session = session_groups[i]
        _, nxt = session_groups[i + 1]
        signal_close = float(session.iloc[-1]["close"])
        signal_low = float(session["low"].min())
        next_close = float(nxt.iloc[-1]["close"])
        next_low = float(nxt["low"].min())
        realized = label_partition(next_close, next_low, signal_close, signal_low)
        for decision_time in DECISION_TIMES:
            elapsed = session[[ts.time() < decision_time for ts in session["local_ct"]]]
            if len(elapsed) < 12:
                continue
            latest = elapsed.iloc[-1]
            weekly_vwap = float(latest["weekly_vwap"])
            if not math.isfinite(weekly_vwap):
                continue
            last6 = elapsed.iloc[-6:]
            above_last6 = last6["close"].to_numpy(float) > last6["weekly_vwap"].to_numpy(float)
            time_acceptance = bool(above_last6.sum() >= 5 and above_last6[-3:].all())
            last12 = elapsed.iloc[-12:]
            typical12 = (last12["high"] + last12["low"] + last12["close"]) / 3.0
            total_volume = float(last12["volume"].sum())
            above_volume = float(last12.loc[typical12 > last12["weekly_vwap"], "volume"].sum())
            volume_fraction = above_volume / total_volume if total_volume > 0 else 0.0
            volume_acceptance = bool(volume_fraction >= 0.60 and float(latest["close"]) > weekly_vwap)
            vpoc = _volume_poc(elapsed)
            tpo_poc = _tpo_poc(elapsed, decision_time)
            spread = (last12["high"] - last12["low"]).replace(0, np.nan)
            clv = (((last12["close"] - last12["low"]) - (last12["high"] - last12["close"])) / spread).fillna(0.0)
            clv_delta = float((clv * last12["volume"]).sum())
            records.append(AcceptanceRecord(
                signal_date=str(signal_date),
                decision_time_ct=decision_time.strftime("%H:%M"),
                week_key=str(latest["week_key"]),
                decision_timestamp=pd.Timestamp(latest["local_ct"]).isoformat(),
                decision_price=round(float(latest["close"]), 6),
                weekly_vwap=round(weekly_vwap, 6),
                session_close=round(signal_close, 6),
                session_low=round(signal_low, 6),
                next_close=round(next_close, 6),
                next_low=round(next_low, 6),
                realized=realized,
                baseline_above_vwap=bool(float(latest["close"]) > weekly_vwap),
                time_acceptance=time_acceptance,
                volume_acceptance=volume_acceptance,
                developing_vpoc_acceptance=bool(math.isfinite(vpoc) and vpoc > weekly_vwap),
                developing_tpo_poc_acceptance=bool(math.isfinite(tpo_poc) and tpo_poc > weekly_vwap),
                clv_delta_proxy_acceptance=bool(clv_delta > 0 and float(latest["close"]) > weekly_vwap),
                volume_fraction_above_vwap=round(volume_fraction, 6),
                developing_vpoc=round(vpoc, 6),
                developing_tpo_poc=round(tpo_poc, 6),
                clv_delta_proxy=round(clv_delta, 6),
            ))
    return records


def _feature_value(record: AcceptanceRecord, feature: str) -> bool:
    return bool(getattr(record, f"{feature}_acceptance"))


def _probabilities(rows: Iterable[AcceptanceRecord], alpha: float = DIRICHLET_ALPHA) -> dict[str, float]:
    counts = Counter(row.realized for row in rows)
    total = sum(counts.values()) + alpha * len(CLASSES)
    probs = {klass: (counts[klass] + alpha) / total for klass in CLASSES}
    if abs(sum(probs.values()) - 1.0) > 1e-12:
        raise AssertionError("probabilities do not sum to one")
    return probs


def _brier(probs: dict[str, float], realized: str) -> float:
    return sum((probs[k] - (1.0 if k == realized else 0.0)) ** 2 for k in CLASSES)


def walk_forward_feature(
    records: list[AcceptanceRecord],
    feature: str,
    *,
    min_train: int = MIN_TRAIN,
    min_state_train: int = MIN_STATE_TRAIN,
) -> list[dict[str, Any]]:
    if feature not in FEATURES:
        raise ValueError(f"unknown feature: {feature}")
    by_time: dict[str, list[AcceptanceRecord]] = defaultdict(list)
    for record in records:
        by_time[record.decision_time_ct].append(record)
    rows: list[dict[str, Any]] = []
    for decision_time, group in sorted(by_time.items()):
        group = sorted(group, key=lambda row: row.signal_date)
        for i in range(min_train, len(group)):
            current = group[i]
            known = group[:i]
            state = _feature_value(current, feature)
            feature_matches = [row for row in known if _feature_value(row, feature) == state]
            baseline_matches = [
                row for row in known if row.baseline_above_vwap == current.baseline_above_vwap
            ]
            model_train = feature_matches if len(feature_matches) >= min_state_train else known
            baseline_train = baseline_matches if len(baseline_matches) >= min_state_train else known
            p_model = _probabilities(model_train)
            p_baseline = _probabilities(baseline_train)
            p_unconditional = _probabilities(known)
            rows.append({
                "feature": feature,
                "signal_date": current.signal_date,
                "decision_time_ct": decision_time,
                "feature_state": state,
                "baseline_state": current.baseline_above_vwap,
                "n_train": len(known),
                "n_feature_state": len(feature_matches),
                "n_baseline_state": len(baseline_matches),
                "p_model": p_model,
                "p_baseline": p_baseline,
                "p_unconditional": p_unconditional,
                "probability_sum_model": sum(p_model.values()),
                "realized": current.realized,
                "brier_model": _brier(p_model, current.realized),
                "brier_baseline": _brier(p_baseline, current.realized),
                "brier_unconditional": _brier(p_unconditional, current.realized),
                "session_close": current.session_close,
                "next_close": current.next_close,
            })
    return rows


def _economics(rows: list[dict[str, Any]], state_key: str, slippage_ticks_per_side: int = 1) -> dict:
    """One MES round trip per signal date, using the earliest accepted decision.

    Pooled rows contain three preregistered decision times per session. Counting
    each as a full independent position would triple-count overlapping exposure
    and inflate CAGR/net PnL. Per-time subsets naturally still contain one row.
    """
    cost = ROUND_TRIP_FEES + 2.0 * slippage_ticks_per_side * TICK_SIZE * MES_MULTIPLIER
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["signal_date"]].append(row)
    trade_rows = []
    for date_rows in by_date.values():
        accepted = sorted(
            (row for row in date_rows if bool(row[state_key])),
            key=lambda row: row["decision_time_ct"],
        )
        if accepted:
            trade_rows.append(accepted[0])
    pnls = [(row["next_close"] - row["session_close"]) * MES_MULTIPLIER - cost for row in trade_rows]
    dates = [date.fromisoformat(row["signal_date"]) for row in trade_rows]
    result = strategy_metrics(pnls, dates)
    result["round_trip_cost"] = cost
    result["signal_rate"] = len(trade_rows) / len(by_date) if by_date else 0.0
    result["unique_signal_dates"] = len(by_date)
    result["overlap_policy"] = "earliest accepted decision per session; maximum one MES round trip per date"
    return result


def summarize_walk_forward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "retained": False}
    by_date: dict[str, list[float]] = defaultdict(list)
    by_date_unconditional: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_date[row["signal_date"]].append(row["brier_baseline"] - row["brier_model"])
        by_date_unconditional[row["signal_date"]].append(
            row["brier_unconditional"] - row["brier_model"]
        )
    date_diffs = pd.Series({d: float(np.mean(v)) for d, v in by_date.items()})
    unconditional_diffs = pd.Series(
        {d: float(np.mean(v)) for d, v in by_date_unconditional.items()}
    )
    bootstrap = paired_block_bootstrap_stats(date_diffs)
    unconditional_bootstrap = paired_block_bootstrap_stats(unconditional_diffs)
    paired_mean = bootstrap["mean"]
    ci_low = bootstrap["ci95_low"]
    ci_high = bootstrap["ci95_high"]
    model_brier = float(np.mean([row["brier_model"] for row in rows]))
    baseline_brier = float(np.mean([row["brier_baseline"] for row in rows]))
    unconditional_brier = float(np.mean([row["brier_unconditional"] for row in rows]))
    model_econ = _economics(rows, "feature_state")
    baseline_econ = _economics(rows, "baseline_state")
    stressed_model = _economics(rows, "feature_state", slippage_ticks_per_side=2)
    return {
        "n": len(rows),
        "n_signal_dates": len(by_date),
        "mean_brier_model": round(model_brier, 6),
        "mean_brier_baseline": round(baseline_brier, 6),
        "mean_brier_unconditional": round(unconditional_brier, 6),
        "paired_diff_baseline_minus_model": round(paired_mean, 6),
        "paired_block_bootstrap_ci95": [round(ci_low, 6), round(ci_high, 6)],
        "paired_block_bootstrap_p_one_sided": round(bootstrap["p_one_sided"], 6),
        "paired_diff_unconditional_minus_model": round(unconditional_bootstrap["mean"], 6),
        "paired_unconditional_block_bootstrap_ci95": [
            round(unconditional_bootstrap["ci95_low"], 6),
            round(unconditional_bootstrap["ci95_high"], 6),
        ],
        "paired_unconditional_block_bootstrap_p_one_sided": round(
            unconditional_bootstrap["p_one_sided"], 6
        ),
        "model_economics": model_econ,
        "baseline_economics": baseline_econ,
        "model_economics_2tick_stress": stressed_model,
        "retained": bool(
            ci_low > 0
            and unconditional_bootstrap["ci95_low"] > 0
            and model_econ.get("expectancy", 0.0) > baseline_econ.get("expectancy", 0.0)
            and stressed_model.get("expectancy", 0.0) > 0
        ),
    }


def records_to_frame(records: list[AcceptanceRecord]) -> pd.DataFrame:
    return pd.DataFrame([asdict(record) for record in records])
