"""
ES read engine (observation only).

At 08:30 CT this locks one directional read for the session from:

* prior RTH initial balance (08:30-09:30 CT) high/low
* overnight high/low (17:00 CT prior day to 08:30 CT)
* ZeroGEX call wall, put wall and gamma flip

The read has exactly one trigger and one invalidation, both fixed at lock
time. Confirmation is two consecutive 5-minute closes beyond the trigger.
At 15:15 CT the read is scored against the RTH 5-minute bars.

Rows go to ``mes_session_hypothesis`` under symbol ``MES_READ`` so they do
not collide with the existing recorder row for ``MES``. The plan and the
scored outcome are stored as JSON in ``gamma_snapshot_json``.

This module never places, routes or stages orders.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")
READ_SYMBOL = "MES_READ"
BARS_SYMBOL = "MES"
PAPER_PORT = 4002
LIVE_PORT = 4001
CT = ZoneInfo("America/Chicago")

RTH_OPEN = time(8, 30)
IB_END = time(9, 30)
RTH_CLOSE = time(15, 0)
OVERNIGHT_START = time(17, 0)
CONFIRM_CLOSES = 2


@dataclass
class ReadPlan:
    side: str  # long | short | skip
    reason: str
    price_at_lock: Optional[float] = None
    trigger: Optional[float] = None
    trigger_source: Optional[str] = None
    invalidation: Optional[float] = None
    invalidation_source: Optional[str] = None
    levels: dict = field(default_factory=dict)


@dataclass
class ReadOutcome:
    status: str  # confirmed_win | confirmed_loss | invalidated | no_trigger | skip | no_data
    entry: Optional[float] = None
    entry_time: Optional[str] = None
    exit: Optional[float] = None
    exit_reason: Optional[str] = None
    delta: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    session_close: Optional[float] = None


# Bars and levels


def _to_ct(bars: Any) -> Optional[pd.DataFrame]:
    """Return bars indexed in CT, or None. Naive timestamps are treated as UTC."""
    if bars is None or not hasattr(bars, "empty") or bars.empty:
        return None
    df = bars.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"]))
        else:
            return None
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    df.index = idx.tz_convert(CT)
    return df.sort_index()


def _window(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    return df[(df.index >= start) & (df.index < end)]


def _ct(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=CT)


def _prior_weekday(d: date) -> date:
    p = d - timedelta(days=1)
    while p.weekday() >= 5:
        p -= timedelta(days=1)
    return p


def collect_levels(bars_ct: Optional[pd.DataFrame], session_date: date, gex: Any) -> dict:
    """Gather candidate levels known at 08:30 CT. Missing inputs are omitted."""
    levels: dict = {}
    if bars_ct is not None:
        prior = _prior_weekday(session_date)
        ib = _window(bars_ct, _ct(prior, RTH_OPEN), _ct(prior, IB_END))
        if not ib.empty:
            levels["ib_high"] = float(ib["high"].max())
            levels["ib_low"] = float(ib["low"].min())
        on = _window(bars_ct, _ct(prior, OVERNIGHT_START), _ct(session_date, RTH_OPEN))
        if not on.empty:
            levels["on_high"] = float(on["high"].max())
            levels["on_low"] = float(on["low"].min())
    if gex is not None:
        for key, attr in (("call_wall", "call_wall"), ("put_wall", "put_wall"), ("flip", "gamma_flip")):
            val = getattr(gex, attr, None)
            if val is not None:
                levels[key] = float(val)
    return levels


def build_plan(levels: dict, price: Optional[float]) -> ReadPlan:
    """Lock one trigger and one invalidation.

    Above the flip the read is long: trigger is the nearest level above
    price, invalidation the nearest level below. Below the flip it is the
    mirror image. Without a flip, a price, or a level on both sides the
    read is skipped.
    """
    if price is None:
        return ReadPlan("skip", "no_price_at_lock", levels=levels)
    flip = levels.get("flip")
    if flip is None:
        return ReadPlan("skip", "no_gamma_flip", price_at_lock=price, levels=levels)

    named = [(k, v) for k, v in levels.items()]
    above = sorted([(v, k) for k, v in named if v > price])
    below = sorted([(v, k) for k, v in named if v < price], reverse=True)
    if not above or not below:
        return ReadPlan("skip", "no_level_on_both_sides", price_at_lock=price, levels=levels)

    if price > flip:
        side, trig, inv = "long", above[0], below[0]
    elif price < flip:
        side, trig, inv = "short", below[0], above[0]
    else:
        return ReadPlan("skip", "price_at_flip", price_at_lock=price, levels=levels)

    return ReadPlan(
        side=side,
        reason=f"price {price:.2f} {'above' if side == 'long' else 'below'} flip {flip:.2f}",
        price_at_lock=price,
        trigger=trig[0],
        trigger_source=trig[1],
        invalidation=inv[0],
        invalidation_source=inv[1],
        levels=levels,
    )


def score_plan(plan: ReadPlan, bars_ct: Optional[pd.DataFrame], session_date: date) -> ReadOutcome:
    """Score a locked plan against RTH 5-minute closes."""
    if bars_ct is None:
        return ReadOutcome("no_data")
    rth = _window(bars_ct, _ct(session_date, RTH_OPEN), _ct(session_date, RTH_CLOSE))
    if rth.empty:
        return ReadOutcome("no_data")
    out = ReadOutcome(
        "skip",
        session_high=float(rth["high"].max()),
        session_low=float(rth["low"].min()),
        session_close=float(rth["close"].iloc[-1]),
    )
    if plan.side not in ("long", "short"):
        out.delta = 0.0
        return out

    sign = 1.0 if plan.side == "long" else -1.0
    beyond_trigger = lambda c: (c - plan.trigger) * sign > 0  # noqa: E731
    beyond_inval = lambda c: (c - plan.invalidation) * sign < 0  # noqa: E731

    run = 0
    entered = False
    for ts, row in rth.iterrows():
        c = float(row["close"])
        if not entered:
            if beyond_inval(c):
                out.status, out.delta = "invalidated", 0.0
                return out
            run = run + 1 if beyond_trigger(c) else 0
            if run >= CONFIRM_CLOSES:
                entered = True
                out.entry, out.entry_time = c, ts.isoformat()
            continue
        if beyond_inval(c):
            out.exit, out.exit_reason = c, "invalidation_close"
            break

    if not entered:
        out.status, out.delta = "no_trigger", 0.0
        return out
    if out.exit is None:
        out.exit, out.exit_reason = out.session_close, "session_close"
    out.delta = round((out.exit - out.entry) * sign, 2)
    out.status = "confirmed_win" if out.delta > 0 else "confirmed_loss"
    return out


# Data access


def ib_data_port_ok(cfg: Any = None) -> bool:
    """True only when the IB data leg points at the paper port."""
    if cfg is None:
        try:
            from config import settings as cfg  # type: ignore
        except Exception:
            return False
    port = getattr(cfg, "IBKR_MARKET_DATA_PORT", None) or getattr(cfg, "IBKR_PORT", None)
    return port == PAPER_PORT


async def _fetch_bars(data_manager: Any, bars_fn: Any, cfg: Any, warnings: list) -> Optional[pd.DataFrame]:
    try:
        if bars_fn is not None:
            return _to_ct(await bars_fn(BARS_SYMBOL))
        if data_manager is None:
            warnings.append("data_manager_unavailable")
            return None
        if not ib_data_port_ok(cfg):
            warnings.append("ib_port_not_paper")
            return None
        raw = await data_manager.get_bars(BARS_SYMBOL, lookback_days=3, timeframe="5m", is_futures=True)
        return _to_ct(raw)
    except Exception as exc:
        logger.warning("[ESRead] bars fetch failed: %s", exc)
        warnings.append(f"bars_failed:{type(exc).__name__}")
        return None


def _gex_dict(gex: Any) -> Optional[dict]:
    if gex is None:
        return None
    d = {k: getattr(gex, k, None) for k in ("contract", "spot", "call_wall", "put_wall", "gamma_flip", "net_gex")}
    fetched = getattr(gex, "fetched_at", None)
    d["fetched_at"] = fetched.isoformat() if isinstance(fetched, datetime) else fetched
    return d


def _table_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mes_session_hypothesis'"
    ).fetchone() is not None


# Public entry points


async def lock_read(
    *,
    for_date: Optional[date] = None,
    db_path: str = DEFAULT_DB_PATH,
    data_manager: Any = None,
    bars_fn: Any = None,
    gex_fn: Any = None,
    cfg: Any = None,
) -> dict:
    """Lock and store the 08:30 CT read. Idempotent per date. Never raises."""
    session_date = for_date or datetime.now(CT).date()
    warnings: list = []

    gex = None
    try:
        if gex_fn is None:
            from data.zerogex_levels import fetch_es_gamma_levels as gex_fn
        gex = gex_fn()
    except Exception as exc:
        warnings.append(f"zerogex_failed:{type(exc).__name__}")
    if gex is None:
        warnings.append("zerogex_unavailable")

    bars_ct = await _fetch_bars(data_manager, bars_fn, cfg, warnings)
    price = None
    if bars_ct is not None:
        pre = bars_ct[bars_ct.index < _ct(session_date, RTH_OPEN)]
        if not pre.empty:
            price = float(pre["close"].iloc[-1])

    plan = build_plan(collect_levels(bars_ct, session_date, gex), price)
    payload = {"plan": asdict(plan), "zerogex": _gex_dict(gex), "warnings": warnings}

    inserted = False
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_exists(conn):
                warnings.append("table_missing")
            else:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO mes_session_hypothesis (
                        date, symbol, recorded_at, gamma_snapshot_json,
                        entry_hypothesis_side, entry_hypothesis_reason, open_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_date.isoformat(),
                        READ_SYMBOL,
                        datetime.now(tz=timezone.utc).isoformat(),
                        json.dumps(payload),
                        plan.side,
                        plan.reason,
                        plan.price_at_lock,
                    ),
                )
                conn.commit()
                inserted = cur.rowcount > 0
    except Exception as exc:
        logger.warning("[ESRead] write failed: %s", exc)
        warnings.append(f"db_failed:{type(exc).__name__}")

    logger.info("[ESRead] %s side=%s trigger=%s inval=%s inserted=%s warnings=%s",
                session_date, plan.side, plan.trigger, plan.invalidation, inserted, warnings)
    return {"inserted": inserted, "date": session_date.isoformat(), **payload}


async def score_reads(
    *,
    for_date: Optional[date] = None,
    db_path: str = DEFAULT_DB_PATH,
    data_manager: Any = None,
    bars_fn: Any = None,
    cfg: Any = None,
) -> dict:
    """Score today's unscored read row. Never raises."""
    session_date = for_date or datetime.now(CT).date()
    summary = {"updated_rows": 0, "skipped_no_data": 0, "errors": []}
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_exists(conn):
                summary["errors"].append("table_missing")
                return summary
            row = conn.execute(
                "SELECT id, gamma_snapshot_json FROM mes_session_hypothesis "
                "WHERE date = ? AND symbol = ? AND outcome_recorded_at IS NULL",
                (session_date.isoformat(), READ_SYMBOL),
            ).fetchone()
        if row is None:
            return summary

        payload = json.loads(row[1] or "{}")
        plan = ReadPlan(**payload.get("plan", {"side": "skip", "reason": "missing_plan"}))
        bars_ct = await _fetch_bars(data_manager, bars_fn, cfg, summary["errors"])
        outcome = score_plan(plan, bars_ct, session_date)
        if outcome.status == "no_data":
            summary["skipped_no_data"] += 1
            return summary

        payload["outcome"] = asdict(outcome)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                UPDATE mes_session_hypothesis
                   SET high_price = ?, low_price = ?, close_price = ?, outcome_delta = ?,
                       outcome_recorded_at = ?, gamma_snapshot_json = ?
                 WHERE id = ? AND outcome_recorded_at IS NULL
                """,
                (
                    outcome.session_high,
                    outcome.session_low,
                    outcome.session_close,
                    outcome.delta,
                    datetime.now(tz=timezone.utc).isoformat(),
                    json.dumps(payload),
                    row[0],
                ),
            )
            conn.commit()
        summary["updated_rows"] = 1
        summary["status"] = outcome.status
    except Exception as exc:
        logger.warning("[ESRead] scoring failed: %s", exc)
        summary["errors"].append(f"score_failed:{type(exc).__name__}")
    return summary


async def _cli_main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else "lock"
    for_date = date.fromisoformat(argv[2]) if len(argv) > 2 else None
    fn = lock_read if mode == "lock" else score_reads
    print(json.dumps(await fn(for_date=for_date), indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(_cli_main(sys.argv)))
