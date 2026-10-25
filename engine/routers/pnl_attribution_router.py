"""
P&L attribution — break the headline number down into where it actually came from.

WHY THIS EXISTS
---------------
`/portfolio/paper/performance` reports a single realisd P&L figure. On
2026-09-25 that figure was +$4,426.57 — but 88% of it came from **MGC**, a
symbol that sits on `DO_NOT_TRADE_SYMBOLS` and can no longer be traded. The one
authorised instrument (MES) contributed $492.72.

A headline total that is dominated by an un-tradeable symbol is not a performance
number, it is a historical artifact. Attribution is what turns "I made money"
into "which decisions made money".

DATA SOURCE
-----------
`paper_trades` in `engine/data/jarvis_trader.db` (read-only). Relevant columns:
  symbol, side, pnl, status, strategy_id, strategy_params, regime,
  slippage_ticks, mae_usd, mfe_usd, stc_contrib, orb_contrib, vwap_contrib

HONESTY NOTES
-------------
- Trades with `strategy_id IS NULL` are reported as ``(unclassified)`` rather
  than being silently dropped or bucketed into a fake strategy.
- ``regime`` is NULL on every closed trade today; that is reported as
  ``coverage: 0%`` rather than presented as a finding.
- Execution-quality fields (slippage/MAE/MFE) are 0% populated. The endpoint
  says so explicitly so a consumer cannot mistake "no data" for "no slippage".
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics", "pnl"])

# Resolved at import time relative to this file's package root.
_DB_PATH = os.environ.get(
    "JARVIS_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "jarvis_trader.db",
    ),
)

# Symbols that may no longer be traded (mirrors config.DO_NOT_TRADE_SYMBOLS).
# Kept as a local constant so this read-only analytics module does not import
# the trading config and can never influence it.
_DO_NOT_TRADE = frozenset({"M2K", "MCL", "MGC", "MNQ"})


def _connect() -> Optional[sqlite3.Connection]:
    if not os.path.exists(_DB_PATH):
        return None
    try:
        con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error as exc:
        logger.warning("pnl-attribution: cannot open db: %s", exc)
        return None


def _group_by(con: sqlite3.Connection, column: str, limit: int = 25) -> list[dict]:
    """Aggregate closed P&L by one column. NULL becomes '(unclassified)'."""
    sql = f"""
        SELECT COALESCE({column}, '(unclassified)') AS bucket,
               COUNT(*)                            AS trades,
               ROUND(SUM(pnl), 2)                  AS total_pnl,
               ROUND(AVG(pnl), 2)                  AS avg_pnl,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
        FROM paper_trades
        WHERE status = 'closed' AND pnl IS NOT NULL
        GROUP BY bucket
        ORDER BY total_pnl DESC
        LIMIT ?
    """
    cur = con.execute(sql, (limit,))
    rows = []
    for r in cur.fetchall():
        trades = r["trades"] or 0
        rows.append(
            {
                "bucket": r["bucket"],
                "trades": trades,
                "total_pnl": r["total_pnl"],
                "avg_pnl": r["avg_pnl"],
                "wins": r["wins"] or 0,
                "losses": r["losses"] or 0,
                "win_rate": round((r["wins"] or 0) / trades, 4) if trades else None,
            }
        )
    return rows


def _coverage(con: sqlite3.Connection) -> dict:
    """Field-population rates, so 'no data' is never mistaken for a zero."""
    cur = con.execute(
        """
        SELECT COUNT(*) AS closed,
               COUNT(strategy_id)    AS strategy_id,
               COUNT(regime)         AS regime,
               COUNT(slippage_ticks) AS slippage,
               COUNT(mae_usd)        AS mae,
               COUNT(mfe_usd)        AS mfe,
               COUNT(stc_contrib)    AS stc
        FROM paper_trades
        WHERE status = 'closed'
        """
    )
    r = cur.fetchone()
    closed = r["closed"] or 0

    def pct(n: int) -> float:
        return round((n / closed) * 100.0, 1) if closed else 0.0

    return {
        "closed_trades": closed,
        "strategy_id_pct": pct(r["strategy_id"] or 0),
        "regime_pct": pct(r["regime"] or 0),
        "slippage_pct": pct(r["slippage"] or 0),
        "mae_pct": pct(r["mae"] or 0),
        "mfe_pct": pct(r["mfe"] or 0),
        "stc_contrib_pct": pct(r["stc"] or 0),
    }


@router.get("/pnl-attribution")
async def pnl_attribution(top_n: int = Query(15, ge=1, le=50)):
    """Realized P&L broken down by symbol, strategy, side and regime.

    Reports ``tradeable_share_pct`` — the fraction of total P&L that came from
    symbols NOT on the do-not-trade list. A high total with a low tradeable
    share means the headline is history, not edge.
    """
    con = _connect()
    if con is None:
        raise HTTPException(status_code=503, detail="trade database unavailable")

    try:
        by_symbol = _group_by(con, "symbol", top_n)
        by_strategy = _group_by(con, "strategy_id", top_n)
        by_side = _group_by(con, "side", 10)
        by_regime = _group_by(con, "regime", 10)
        coverage = _coverage(con)

        cur = con.execute(
            "SELECT COUNT(*) AS n, ROUND(SUM(pnl), 2) AS total "
            "FROM paper_trades WHERE status='closed' AND pnl IS NOT NULL"
        )
        head = cur.fetchone()
        total_pnl = head["total"] or 0.0
    except sqlite3.Error as exc:
        logger.warning("pnl-attribution query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"query failed: {exc}") from exc
    finally:
        con.close()

    # Tradeable share: P&L from symbols that are NOT blocked.
    tradeable_pnl = sum(
        (row["total_pnl"] or 0.0)
        for row in by_symbol
        if str(row["bucket"]).upper() not in _DO_NOT_TRADE
    )
    blocked_pnl = sum(
        (row["total_pnl"] or 0.0)
        for row in by_symbol
        if str(row["bucket"]).upper() in _DO_NOT_TRADE
    )
    tradeable_share = round((tradeable_pnl / total_pnl) * 100.0, 1) if total_pnl else None

    return {
        "total_pnl": total_pnl,
        "closed_trades": head["n"] or 0,
        "tradeable_pnl": round(tradeable_pnl, 2),
        "blocked_pnl": round(blocked_pnl, 2),
        "tradeable_share_pct": tradeable_share,
        "do_not_trade_symbols": sorted(_DO_NOT_TRADE),
        "by_symbol": by_symbol,
        "by_strategy": by_strategy,
        "by_side": by_side,
        "by_regime": by_regime,
        "field_coverage": coverage,
        "source": "paper_trades (read-only)",
    }
