"""
MES session hypothesis forward-recorder (morning pass).

Runs at 08:30 CT each weekday. Reads the pre-open state — Corey bias + gamma
levels + IB levels — derives a directional hypothesis, and writes one row
into the ``mes_session_hypothesis`` table. The paired outcome job
(``mes_session_outcome.py``) fills in high/low/close and the outcome delta
at 15:15 CT after the session closes.

Why this exists
---------------
MES 1h grid-search (40 random + 25 STC-focused combos, 2026-04-20) concluded
that no standard-indicator parameter set produces PF >= 2.0 on cached OHLC.
The honest next move is to test whether fundamentally *different* signals
(Corey's directional bias from #market-updates + gamma positioning from the
TradingView "MY FREE GAMMA LEVELS" overlay) predict MES session direction.

Those signals have no historical archive — gamma levels are sourced from a
closed-source TradingView overlay and only exposed via live CLI reads; Corey
bias only reaches back to 2026-03-25 and has ~16 rows. A walk-forward
backtest is not constructible today, so we record forward and evaluate
after ~8-12 weeks of accumulated rows.

Design notes
------------
* Graceful degradation: every signal source can fail independently and the
  row is still written with NULL fields + a ``warnings`` entry in the
  hypothesis reason. We prefer a partial row to no row.
* No trading action: this module is observational. It does not interact
  with the live R3 pipeline, the safety layer, or any notifier.
* Idempotent: the table has UNIQUE(date, symbol). A second call on the same
  day updates nothing (INSERT OR IGNORE). If you need to force-refresh a
  day's hypothesis, delete the row first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")
DEFAULT_SYMBOL = "MES"

# Hypothesis thresholds — kept here (not in config) so the experiment has
# a fixed, traceable signal-to-hypothesis mapping across weeks. Any change
# here should be a conscious commit so the experiment stays interpretable.
MIN_CONVICTION = 0.5
REQUIRED_DATA_QUALITY = "fresh"


# ── Internal helpers ─────────────────────────────────────────────────────────


def _gamma_snapshot_to_dict(snapshot: Any) -> dict:
    """Pull the gamma fields off a TVIndicatorSnapshot into a stable dict shape.

    Returns at minimum `{"data_quality": "unavailable"}` when snapshot is None
    or empty. Never raises.
    """
    if snapshot is None:
        return {"data_quality": "unavailable"}
    fields = (
        "gex_flip",
        "call_wall",
        "put_wall",
        "hvl",
        "vol_trigger_up",
        "vol_trigger_down",
        "max_pain",
    )
    out: dict = {"data_quality": getattr(snapshot, "data_quality", "unavailable")}
    for f in fields:
        out[f] = getattr(snapshot, f, None)
    return out


def _derive_hypothesis(corey_bias: Any, gamma: dict) -> tuple[str, str]:
    """Return (side, reason) for the session hypothesis.

    side ∈ {"long", "short", "skip"}. Reason is a short string describing
    why that side was chosen — surfaced in the row so we can re-analyze
    later without re-running the derivation.
    """
    directional = getattr(corey_bias, "directional_bias", "neutral") or "neutral"
    conviction = float(getattr(corey_bias, "conviction", 0.0) or 0.0)
    data_quality = getattr(corey_bias, "data_quality", "none")

    if data_quality != REQUIRED_DATA_QUALITY:
        return "skip", f"corey_bias_data_quality={data_quality}"
    if conviction < MIN_CONVICTION:
        return "skip", f"corey_conviction={conviction:.2f}<{MIN_CONVICTION}"
    if directional == "bullish":
        return "long", f"corey=bullish conv={conviction:.2f}"
    if directional == "bearish":
        return "short", f"corey=bearish conv={conviction:.2f}"
    return "skip", f"corey_directional={directional}"


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='mes_session_hypothesis'"
    ).fetchone()
    return row is not None


# ── Public entry points ──────────────────────────────────────────────────────


@dataclass
class RecordResult:
    """Return value of record_session — machine-readable outcome of one run."""

    inserted: bool = False
    date: Optional[str] = None
    symbol: str = DEFAULT_SYMBOL
    hypothesis_side: Optional[str] = None
    hypothesis_reason: Optional[str] = None
    open_price: Optional[float] = None
    warnings: list[str] = None  # populated if signal sources degraded

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> dict:
        return {
            "inserted": self.inserted,
            "date": self.date,
            "symbol": self.symbol,
            "hypothesis_side": self.hypothesis_side,
            "hypothesis_reason": self.hypothesis_reason,
            "open_price": self.open_price,
            "warnings": list(self.warnings),
        }


async def record_session(
    *,
    for_date: Optional[date] = None,
    symbol: str = DEFAULT_SYMBOL,
    db_path: str = DEFAULT_DB_PATH,
    data_manager: Any = None,
    briefing_fn: Any = None,
    tv_bridge: Any = None,
) -> RecordResult:
    """Write one morning-pass row to ``mes_session_hypothesis``.

    Dependencies are injectable for testing. When any of them are None the
    corresponding production signal source is looked up lazily.

    Returns a RecordResult. Never raises — errors are captured in warnings.
    """
    target_date = for_date or date.today()
    result = RecordResult(date=target_date.isoformat(), symbol=symbol)

    # --- Corey bias + IB levels (via DiscordBriefing facade) ---
    corey_bias: Any = None
    ib_levels: Optional[dict] = None
    try:
        if briefing_fn is None:
            from discord.briefing import get_discord_briefing as briefing_fn  # type: ignore
        briefing = await briefing_fn(symbol, for_date=target_date)
        corey_bias = getattr(briefing, "corey_bias", None)
        ib_levels = getattr(briefing, "ib_levels", None)
    except Exception as exc:  # pragma: no cover — facade is designed not to raise
        logger.warning("[MESRecorder] DiscordBriefing failed: %s", exc)
        result.warnings.append(f"briefing_failed:{type(exc).__name__}")

    # --- Gamma snapshot (via TV bridge) ---
    gamma_snap: Any = None
    try:
        if tv_bridge is None:
            from data.tv_indicator_bridge import get_tv_bridge
            tv_bridge = get_tv_bridge()
        gamma_snap = tv_bridge.get_snapshot(symbol)
    except Exception as exc:  # pragma: no cover — bridge is designed not to raise
        logger.warning("[MESRecorder] TV bridge snapshot failed: %s", exc)
        result.warnings.append(f"tv_bridge_failed:{type(exc).__name__}")
    gamma_dict = _gamma_snapshot_to_dict(gamma_snap)

    # --- Open price (via data manager; may be None if offline) ---
    open_price: Optional[float] = None
    if data_manager is not None:
        try:
            px = await data_manager.get_current_price(symbol)
            if isinstance(px, dict):
                raw = px.get("last_price")
                if raw is not None:
                    open_price = float(raw)
        except Exception as exc:
            logger.warning("[MESRecorder] Price fetch failed: %s", exc)
            result.warnings.append(f"price_failed:{type(exc).__name__}")
    else:
        result.warnings.append("data_manager_unavailable")
    result.open_price = open_price

    # --- Derive hypothesis ---
    side, reason = _derive_hypothesis(corey_bias, gamma_dict)
    result.hypothesis_side = side
    result.hypothesis_reason = reason

    # --- Insert (idempotent via UNIQUE(date,symbol)) ---
    with sqlite3.connect(db_path) as conn:
        if not _table_exists(conn):
            logger.error(
                "[MESRecorder] mes_session_hypothesis table missing; "
                "run database/migrations.py first."
            )
            result.warnings.append("table_missing")
            return result

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO mes_session_hypothesis (
                date, symbol, recorded_at,
                corey_bias, corey_conviction, corey_session_type,
                corey_ib_bias, corey_data_quality,
                gamma_snapshot_json, ib_levels_json,
                entry_hypothesis_side, entry_hypothesis_reason,
                open_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_date.isoformat(),
                symbol,
                datetime.now(tz=timezone.utc).isoformat(),
                getattr(corey_bias, "directional_bias", None),
                getattr(corey_bias, "conviction", None),
                getattr(corey_bias, "session_type", None),
                getattr(corey_bias, "ib_bias", None),
                getattr(corey_bias, "data_quality", None),
                json.dumps(gamma_dict),
                json.dumps(ib_levels) if ib_levels is not None else None,
                side,
                reason,
                open_price,
            ),
        )
        conn.commit()
        result.inserted = cur.rowcount > 0

    if result.inserted:
        logger.info(
            "[MESRecorder] wrote %s/%s hypothesis=%s (%s) open=%s gamma=%s warnings=%s",
            target_date.isoformat(),
            symbol,
            side,
            reason,
            open_price,
            gamma_dict.get("data_quality"),
            result.warnings,
        )
    else:
        logger.info(
            "[MESRecorder] row already exists for %s/%s — skipped (idempotent)",
            target_date.isoformat(),
            symbol,
        )

    return result


# ── CLI entry (for ad-hoc runs + smoke tests) ────────────────────────────────


async def _cli_main(argv: list[str]) -> int:
    symbol = argv[1] if len(argv) > 1 else DEFAULT_SYMBOL
    result = await record_session(symbol=symbol)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.inserted or "table_missing" not in result.warnings else 1


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(_cli_main(sys.argv)))
