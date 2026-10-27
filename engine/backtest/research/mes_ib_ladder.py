"""Causal MES initial-balance ladder study.

The completed IB is never exposed before 09:30 CT. This module is analysis-only
and has no dependency on runtime config, broker state, or order routing.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from backtest.deflated_sharpe import deflated_sharpe_empirical
from backtest.research.session_data import (
    INITIAL_CAPITAL,
    MES_MULTIPLIER,
    ROUND_TRIP_FEES,
    TICK_SIZE,
    SessionSlice,
    strategy_metrics,
)

EntryMode = Literal["stop_entry", "close_confirm"]
StopMode = Literal["ib_mid", "opposite_ib"]
TargetMode = Literal["overnight", "half_ib", "full_ib", "ladder"]
ENTRY_MODES: tuple[EntryMode, ...] = ("stop_entry", "close_confirm")
STOP_MODES: tuple[StopMode, ...] = ("ib_mid", "opposite_ib")
TARGET_MODES: tuple[TargetMode, ...] = ("overnight", "half_ib", "full_ib", "ladder")


@dataclass(frozen=True)
class EntrySignal:
    direction: int
    timestamp: pd.Timestamp
    bar_position: int
    raw_entry: float
    ambiguous: bool = False


@dataclass(frozen=True)
class TradeOutcome:
    trade_date: str
    config_id: str
    entry_mode: str
    stop_mode: str
    target_mode: str
    slippage_ticks_per_side: int
    direction: int
    entry_time: str
    exit_time: str
    raw_entry: float
    stop_price: float
    raw_exit_average: float
    contracts_entered: int
    target_fills: int
    exit_reason: str
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    mfe_points: float
    mae_points: float
    minutes_to_exit: float
    overnight_target_eligible: bool
    ledger_reconciliation_residual: float


@dataclass(frozen=True)
class LadderEvent:
    trade_date: str
    break_direction: int
    break_time: str | None
    ambiguous_break: bool
    ib_high: float
    ib_low: float
    ib_width: float
    overnight_high: float
    overnight_low: float
    overnight_target_eligible: bool
    overnight_target_hit: bool
    half_extension_hit: bool
    full_extension_hit: bool


def _entry_signal(session: SessionSlice, mode: EntryMode) -> EntrySignal | None:
    ib_high = float(session.ib["high"].max())
    ib_low = float(session.ib["low"].min())
    for pos, (ts, bar) in enumerate(session.post_ib.iterrows()):
        if mode == "stop_entry":
            up = float(bar["high"]) >= ib_high
            down = float(bar["low"]) <= ib_low
        else:
            up = float(bar["close"]) > ib_high
            down = float(bar["close"]) < ib_low
        if up and down:
            return EntrySignal(0, ts, pos, float(bar["close"]), ambiguous=True)
        if up:
            return EntrySignal(1, ts, pos, ib_high if mode == "stop_entry" else float(bar["close"]))
        if down:
            return EntrySignal(-1, ts, pos, ib_low if mode == "stop_entry" else float(bar["close"]))
    return None


def _target_map(session: SessionSlice, signal: EntrySignal) -> tuple[dict[str, float], bool]:
    ib_high = float(session.ib["high"].max())
    ib_low = float(session.ib["low"].min())
    width = ib_high - ib_low
    overnight_high = float(session.overnight["high"].max())
    overnight_low = float(session.overnight["low"].min())
    if signal.direction > 0:
        overnight = overnight_high
        eligible = overnight > signal.raw_entry
        return {
            "overnight": overnight,
            "half_ib": ib_high + 0.5 * width,
            "full_ib": ib_high + width,
        }, eligible
    overnight = overnight_low
    eligible = overnight < signal.raw_entry
    return {
        "overnight": overnight,
        "half_ib": ib_low - 0.5 * width,
        "full_ib": ib_low - width,
    }, eligible


def _stop_price(session: SessionSlice, direction: int, mode: StopMode) -> float:
    ib_high = float(session.ib["high"].max())
    ib_low = float(session.ib["low"].min())
    if mode == "ib_mid":
        return (ib_high + ib_low) / 2.0
    return ib_low if direction > 0 else ib_high


def _ordered_targets(targets: dict[str, float], signal: EntrySignal, mode: TargetMode, overnight_ok: bool) -> list[tuple[str, float]]:
    if mode == "overnight":
        return [("overnight", targets["overnight"])] if overnight_ok else []
    if mode == "half_ib":
        return [("half_ib", targets["half_ib"])]
    if mode == "full_ib":
        return [("full_ib", targets["full_ib"])]
    selected = [(name, value) for name, value in targets.items() if name != "overnight" or overnight_ok]
    return sorted(selected, key=lambda item: signal.direction * (item[1] - signal.raw_entry))


def simulate_trade(
    session: SessionSlice,
    *,
    entry_mode: EntryMode,
    stop_mode: StopMode,
    target_mode: TargetMode,
    slippage_ticks_per_side: int,
) -> TradeOutcome | None:
    signal = _entry_signal(session, entry_mode)
    if signal is None or signal.ambiguous or signal.direction == 0:
        return None
    targets, overnight_ok = _target_map(session, signal)
    ordered = _ordered_targets(targets, signal, target_mode, overnight_ok)
    if not ordered:
        return None
    stop = _stop_price(session, signal.direction, stop_mode)
    bars = session.post_ib.iloc[signal.bar_position :]
    # A close-confirm entry occurs at the close of its signal bar, so its range
    # cannot generate a same-bar stop/target. Stop entries are live intrabar.
    eval_bars = bars if entry_mode == "stop_entry" else bars.iloc[1:]
    contracts = len(ordered)
    remaining = contracts
    fills: list[tuple[str, float, int, pd.Timestamp]] = []
    exit_time = signal.timestamp
    exit_reason = "rth_close"
    target_fills = 0
    extrema_bars = eval_bars if not eval_bars.empty else bars.iloc[-1:]
    for ts, bar in eval_bars.iterrows():
        low, high = float(bar["low"]), float(bar["high"])
        stop_hit = low <= stop if signal.direction > 0 else high >= stop
        reachable = [
            (name, px)
            for name, px in ordered
            if (high >= px if signal.direction > 0 else low <= px)
        ]
        # Conservative bar-order rule: an ambiguous stop+target bar stops first.
        if stop_hit:
            fills.append(("stop", stop, remaining, ts))
            exit_time = ts
            exit_reason = "stop"
            remaining = 0
            break
        if reachable:
            for name, px in reachable:
                fills.append((name, px, 1, ts))
                ordered.remove((name, px))
                target_fills += 1
                remaining -= 1
                exit_time = ts
                exit_reason = "all_targets" if remaining == 0 else "partial_targets"
            if remaining == 0:
                break
    if remaining > 0:
        last_ts = session.rth.index[-1]
        fills.append(("rth_close", float(session.rth.iloc[-1]["close"]), remaining, last_ts))
        exit_time = last_ts
        exit_reason = "rth_close" if target_fills == 0 else "partial_then_close"

    raw_exit_average = sum(px * qty for _, px, qty, _ in fills) / contracts
    gross = sum(signal.direction * (px - signal.raw_entry) * MES_MULTIPLIER * qty for _, px, qty, _ in fills)
    fees = ROUND_TRIP_FEES * contracts
    slippage = 2.0 * slippage_ticks_per_side * TICK_SIZE * MES_MULTIPLIER * contracts
    net = gross - fees - slippage
    residual = net - (gross - fees - slippage)
    max_high = float(extrema_bars.loc[:exit_time, "high"].max())
    min_low = float(extrema_bars.loc[:exit_time, "low"].min())
    if signal.direction > 0:
        mfe, mae = max_high - signal.raw_entry, signal.raw_entry - min_low
    else:
        mfe, mae = signal.raw_entry - min_low, max_high - signal.raw_entry
    config_id = f"{entry_mode}__{stop_mode}__{target_mode}__slip{slippage_ticks_per_side}"
    return TradeOutcome(
        trade_date=str(session.trade_date),
        config_id=config_id,
        entry_mode=entry_mode,
        stop_mode=stop_mode,
        target_mode=target_mode,
        slippage_ticks_per_side=slippage_ticks_per_side,
        direction=signal.direction,
        entry_time=signal.timestamp.isoformat(),
        exit_time=exit_time.isoformat(),
        raw_entry=round(signal.raw_entry, 6),
        stop_price=round(stop, 6),
        raw_exit_average=round(raw_exit_average, 6),
        contracts_entered=contracts,
        target_fills=target_fills,
        exit_reason=exit_reason,
        gross_pnl=round(gross, 6),
        fees=round(fees, 6),
        slippage_cost=round(slippage, 6),
        net_pnl=round(net, 6),
        mfe_points=round(max(mfe, 0.0), 6),
        mae_points=round(max(mae, 0.0), 6),
        minutes_to_exit=round((exit_time - signal.timestamp).total_seconds() / 60.0, 6),
        overnight_target_eligible=overnight_ok,
        ledger_reconciliation_residual=round(residual, 12),
    )


def simulate_simple_ib_break(
    session: SessionSlice,
    *,
    slippage_ticks_per_side: int,
) -> TradeOutcome | None:
    """Benchmark: first stop-entry IB break, opposite-IB stop, otherwise RTH close."""
    signal = _entry_signal(session, "stop_entry")
    if signal is None or signal.ambiguous or signal.direction == 0:
        return None
    stop = _stop_price(session, signal.direction, "opposite_ib")
    bars = session.post_ib.iloc[signal.bar_position :]
    exit_time = session.rth.index[-1]
    raw_exit = float(session.rth.iloc[-1]["close"])
    reason = "rth_close"
    for ts, bar in bars.iterrows():
        if (signal.direction > 0 and float(bar["low"]) <= stop) or (
            signal.direction < 0 and float(bar["high"]) >= stop
        ):
            exit_time, raw_exit, reason = ts, stop, "stop"
            break
    eval_bars = bars.loc[:exit_time]
    max_high = float(eval_bars["high"].max())
    min_low = float(eval_bars["low"].min())
    mfe = max_high - signal.raw_entry if signal.direction > 0 else signal.raw_entry - min_low
    mae = signal.raw_entry - min_low if signal.direction > 0 else max_high - signal.raw_entry
    gross = signal.direction * (raw_exit - signal.raw_entry) * MES_MULTIPLIER
    fees = ROUND_TRIP_FEES
    slippage = 2.0 * slippage_ticks_per_side * TICK_SIZE * MES_MULTIPLIER
    net = gross - fees - slippage
    return TradeOutcome(
        trade_date=str(session.trade_date),
        config_id=f"simple_ib_break__slip{slippage_ticks_per_side}",
        entry_mode="stop_entry",
        stop_mode="opposite_ib",
        target_mode="rth_close",
        slippage_ticks_per_side=slippage_ticks_per_side,
        direction=signal.direction,
        entry_time=signal.timestamp.isoformat(),
        exit_time=exit_time.isoformat(),
        raw_entry=round(signal.raw_entry, 6),
        stop_price=round(stop, 6),
        raw_exit_average=round(raw_exit, 6),
        contracts_entered=1,
        target_fills=0,
        exit_reason=reason,
        gross_pnl=round(gross, 6),
        fees=round(fees, 6),
        slippage_cost=round(slippage, 6),
        net_pnl=round(net, 6),
        mfe_points=round(max(mfe, 0.0), 6),
        mae_points=round(max(mae, 0.0), 6),
        minutes_to_exit=round((exit_time - signal.timestamp).total_seconds() / 60.0, 6),
        overnight_target_eligible=False,
        ledger_reconciliation_residual=round(net - (gross - fees - slippage), 12),
    )


def ladder_event(session: SessionSlice) -> LadderEvent:
    ib_high = float(session.ib["high"].max())
    ib_low = float(session.ib["low"].min())
    width = ib_high - ib_low
    signal = _entry_signal(session, "stop_entry")
    if signal is None:
        return LadderEvent(
            str(session.trade_date), 0, None, False, ib_high, ib_low, width,
            float(session.overnight["high"].max()), float(session.overnight["low"].min()),
            False, False, False, False,
        )
    if signal.ambiguous:
        return LadderEvent(
            str(session.trade_date), 0, signal.timestamp.isoformat(), True, ib_high, ib_low, width,
            float(session.overnight["high"].max()), float(session.overnight["low"].min()),
            False, False, False, False,
        )
    future = session.post_ib.iloc[signal.bar_position :]
    on_high = float(session.overnight["high"].max())
    on_low = float(session.overnight["low"].min())
    if signal.direction > 0:
        eligible = on_high > ib_high
        return LadderEvent(
            str(session.trade_date), 1, signal.timestamp.isoformat(), False, ib_high, ib_low, width,
            on_high, on_low, eligible,
            bool(eligible and float(future["high"].max()) >= on_high),
            bool(float(future["high"].max()) >= ib_high + 0.5 * width),
            bool(float(future["high"].max()) >= ib_high + width),
        )
    eligible = on_low < ib_low
    return LadderEvent(
        str(session.trade_date), -1, signal.timestamp.isoformat(), False, ib_high, ib_low, width,
        on_high, on_low, eligible,
        bool(eligible and float(future["low"].min()) <= on_low),
        bool(float(future["low"].min()) <= ib_low - 0.5 * width),
        bool(float(future["low"].min()) <= ib_low - width),
    )


def summarize_events(events: list[LadderEvent]) -> dict:
    non_ambiguous = [e for e in events if not e.ambiguous_break]
    breaks = [e for e in non_ambiguous if e.break_direction]
    overnight = [e for e in breaks if e.overnight_target_eligible]
    half_hits = [e for e in breaks if e.half_extension_hit]
    return {
        "sessions": len(events),
        "ambiguous_first_break_sessions": sum(e.ambiguous_break for e in events),
        "sessions_with_ib_break": len(breaks),
        "ib_break_rate": len(breaks) / len(non_ambiguous) if non_ambiguous else 0.0,
        "long_first_breaks": sum(e.break_direction > 0 for e in breaks),
        "short_first_breaks": sum(e.break_direction < 0 for e in breaks),
        "overnight_target_eligible": len(overnight),
        "overnight_hit_rate_conditional": (
            sum(e.overnight_target_hit for e in overnight) / len(overnight) if overnight else 0.0
        ),
        "half_extension_hit_rate_given_break": (
            sum(e.half_extension_hit for e in breaks) / len(breaks) if breaks else 0.0
        ),
        "full_extension_hit_rate_given_half": (
            sum(e.full_extension_hit for e in half_hits) / len(half_hits) if half_hits else 0.0
        ),
    }


def summarize_trades(
    trades: list[TradeOutcome],
    *,
    n_trials: int,
    dsr_permutations: int = 2000,
) -> dict:
    pnls = [t.net_pnl for t in trades]
    dates = [date.fromisoformat(t.trade_date) for t in trades]
    summary = strategy_metrics(pnls, dates)
    summary.update({
        "long_trades": sum(t.direction > 0 for t in trades),
        "short_trades": sum(t.direction < 0 for t in trades),
        "contracts_round_tripped": sum(t.contracts_entered for t in trades),
        "mean_mfe_points": round(float(np.mean([t.mfe_points for t in trades])), 6) if trades else 0.0,
        "median_mfe_points": round(float(np.median([t.mfe_points for t in trades])), 6) if trades else 0.0,
        "mean_mae_points": round(float(np.mean([t.mae_points for t in trades])), 6) if trades else 0.0,
        "median_mae_points": round(float(np.median([t.mae_points for t in trades])), 6) if trades else 0.0,
        "mean_minutes_to_exit": round(float(np.mean([t.minutes_to_exit for t in trades])), 6) if trades else 0.0,
        "ledger_reconciliation_residual": round(sum(t.ledger_reconciliation_residual for t in trades), 12),
        "gross_pnl": round(sum(t.gross_pnl for t in trades), 6),
        "fees": round(sum(t.fees for t in trades), 6),
        "slippage_cost": round(sum(t.slippage_cost for t in trades), 6),
        "n_trials_dsr": n_trials,
    })
    if len(trades) >= 3 and dsr_permutations > 0:
        summary["dsr"] = deflated_sharpe_empirical(
            pnls,
            n_trials=n_trials,
            initial_capital=INITIAL_CAPITAL,
            n_permutations=dsr_permutations,
        )
    else:
        summary["dsr"] = {
            "dsr": None if dsr_permutations <= 0 else 0.0,
            "n_obs": len(trades),
            "n_trials": n_trials,
            "status": "not_computed" if dsr_permutations <= 0 else "insufficient_sample",
        }
    return summary


def run_family(
    sessions: list[SessionSlice],
    *,
    slippage_ticks_per_side: int,
    n_trials: int,
    dsr_permutations: int = 0,
) -> tuple[list[TradeOutcome], dict[str, dict]]:
    trades: list[TradeOutcome] = []
    summaries: dict[str, dict] = {}
    for entry_mode in ENTRY_MODES:
        for stop_mode in STOP_MODES:
            for target_mode in TARGET_MODES:
                config_trades = [
                    outcome
                    for session in sessions
                    if (
                        outcome := simulate_trade(
                            session,
                            entry_mode=entry_mode,
                            stop_mode=stop_mode,
                            target_mode=target_mode,
                            slippage_ticks_per_side=slippage_ticks_per_side,
                        )
                    )
                    is not None
                ]
                trades.extend(config_trades)
                config_id = f"{entry_mode}__{stop_mode}__{target_mode}__slip{slippage_ticks_per_side}"
                summaries[config_id] = summarize_trades(
                    config_trades,
                    n_trials=n_trials,
                    dsr_permutations=dsr_permutations,
                )
    return trades, summaries


def outcomes_to_frame(outcomes: list[TradeOutcome]) -> pd.DataFrame:
    return pd.DataFrame([asdict(outcome) for outcome in outcomes])


def events_to_frame(events: list[LadderEvent]) -> pd.DataFrame:
    return pd.DataFrame([asdict(event) for event in events])


def chronological_split(sessions: list[SessionSlice], train_fraction: float = 0.60) -> tuple[list[SessionSlice], list[SessionSlice]]:
    cut = max(1, min(len(sessions) - 1, int(math.floor(len(sessions) * train_fraction))))
    return sessions[:cut], sessions[cut:]


def expanding_windows(sessions: list[SessionSlice], min_train: int = 200, test_size: int = 40) -> list[tuple[list[SessionSlice], list[SessionSlice]]]:
    windows: list[tuple[list[SessionSlice], list[SessionSlice]]] = []
    start = min_train
    while start < len(sessions):
        end = min(len(sessions), start + test_size)
        windows.append((sessions[:start], sessions[start:end]))
        start = end
    return windows
