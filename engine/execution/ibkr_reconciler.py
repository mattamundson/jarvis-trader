"""
IBKR Fill Reconciler
====================
Imports raw execution fills from the live IBGatewayManager into the
`ibkr_fills` SQLite table.  Uses exec_id as the primary key so imports are
idempotent — calling reconcile() multiple times never creates duplicates.

This covers the DUP662235 demo account where 90 MES + 37 MNQ contracts exist
in IBKR but were never submitted through JARVIS (ALLOW_PAPER_SIMULATED_ORDERS
is False, so the IBKR-facing path was never exercised).  The reconciler gives
JARVIS read-side visibility into those fills without touching paper_trades or
the order-routing pipeline.

Usage (from brokers_router.py):
    reconciler = IBKRReconciler(db_path, real_ibkr_manager)
    result = await reconciler.reconcile()
    # result: {"imported": N, "total_in_db": M, "fills": [...]}
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class IBKRReconciler:
    """
    Syncs live IBKR execution fills into the local ibkr_fills table.

    Parameters
    ----------
    db_path : str | Path
        Path to the JARVIS SQLite database (jarvis_trader.db).
    data_manager : MarketDataManager
        Passed at injection time; `data_manager.ibkr` is resolved lazily on each
        reconcile() call because the IBKRDataConnector is initialized asynchronously
        after the router is wired (background init runs after FastAPI lifespan).
    """

    def __init__(self, db_path: str | Path, data_manager: Any) -> None:
        self._db_path = str(db_path)
        self._dm = data_manager

    def _get_connector(self):
        """Resolve the IBKRDataConnector lazily from data_manager.ibkr."""
        if self._dm is None:
            return None
        ibkr = getattr(self._dm, "ibkr", None)
        if ibkr is None:
            logger.warning(
                "IBKRReconciler: data_manager.ibkr is None — "
                "background init may not have completed yet"
            )
        return ibkr

    async def reconcile(self) -> dict:
        """
        Fetch fills from IBKR and upsert into ibkr_fills.

        data_manager.ibkr is resolved lazily because background init (which
        creates the IBKRDataConnector and connects) runs after the router is
        wired at startup.

        Returns
        -------
        dict with:
            imported    : int  — number of NEW fills inserted this call
            skipped     : int  — fills already in DB (exec_id collision)
            total_in_db : int  — total ibkr_fills rows after import
            fills_from_ib: int — raw fills returned by IBKR
            connected   : bool — whether the gateway was reachable
        """
        fills: list[dict] = []
        gw = self._get_connector()
        connected = gw is not None

        if not connected:
            logger.warning("IBKRReconciler: no gateway — skipping reconcile")
            return self._summary(fills, imported=0, skipped=0, connected=False)

        try:
            fills = await gw.get_executions()
        except Exception as exc:
            logger.error("IBKRReconciler get_executions failed: %s", exc)
            connected = False

        imported = 0
        skipped = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        if fills:
            try:
                with closing(sqlite3.connect(self._db_path)) as conn:
                    for fill in fills:
                        exec_id = fill.get("exec_id", "")
                        if not exec_id:
                            continue
                        existing = conn.execute(
                            "SELECT 1 FROM ibkr_fills WHERE exec_id = ?", (exec_id,)
                        ).fetchone()
                        if existing:
                            skipped += 1
                            continue
                        conn.execute(
                            """
                            INSERT INTO ibkr_fills
                                (exec_id, account, symbol, sec_type, expiry, side,
                                 quantity, price, avg_price, commission, exchange,
                                 currency, fill_time, order_id, imported_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                exec_id,
                                fill.get("account", ""),
                                fill.get("symbol", ""),
                                fill.get("sec_type", "FUT"),
                                fill.get("expiry", ""),
                                fill.get("side", ""),
                                fill.get("quantity", 0.0),
                                fill.get("price", 0.0),
                                fill.get("avg_price"),
                                fill.get("commission"),
                                fill.get("exchange"),
                                fill.get("currency", "USD"),
                                fill.get("fill_time", ""),
                                fill.get("order_id"),
                                now_iso,
                            ),
                        )
                        imported += 1
                    conn.commit()
            except Exception as exc:
                logger.error("IBKRReconciler DB write failed: %s", exc)

        return self._summary(fills, imported=imported, skipped=skipped, connected=connected)

    def get_fills(
        self,
        symbol: Optional[str] = None,
        account: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Read cached fills from ibkr_fills.

        Parameters
        ----------
        symbol  : filter by symbol (e.g. "MES"), case-insensitive
        account : filter by account ID (e.g. "DUP662235")
        limit   : max rows returned (ordered by fill_time DESC)
        """
        try:
            with closing(sqlite3.connect(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                clauses = []
                params: list = []
                if symbol:
                    clauses.append("UPPER(symbol) = UPPER(?)")
                    params.append(symbol)
                if account:
                    clauses.append("account = ?")
                    params.append(account)
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params.append(limit)
                rows = conn.execute(
                    f"SELECT * FROM ibkr_fills {where} ORDER BY fill_time DESC LIMIT ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("IBKRReconciler get_fills failed: %s", exc)
            return []

    def import_csv_positions(self, csv_path: str, statement_date: str = "") -> dict:
        """
        Import open Futures positions from an IBKR activity-statement CSV as
        synthetic fills.  exec_id = 'CSV_POS_{account}_{symbol}_{date}' so
        repeated calls are idempotent and records are distinguishable from live
        fills returned by reqExecutionsAsync.

        Only Futures rows in the 'Open Positions' section are imported;
        Stocks and other asset classes are skipped.
        """
        import csv as _csv

        account = "DUP662235"
        parsed: list[dict] = []

        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for row in _csv.reader(fh):
                    if len(row) < 5:
                        continue
                    # Extract account ID from the Statement header section
                    if row[0] == "Account Information" and row[1] == "Data" and row[2] == "Account":
                        raw = row[3].split("(")[0].strip()
                        if raw:
                            account = raw
                        continue
                    # Open Positions,Data,Summary,Futures,USD,SYMBOL,QTY,MULT,COST_PRICE,...
                    if (
                        row[0] == "Open Positions"
                        and row[1] == "Data"
                        and row[2] == "Summary"
                        and row[3].strip() == "Futures"
                        and len(row) >= 9
                    ):
                        try:
                            parsed.append(
                                {
                                    "currency": row[4].strip(),
                                    "symbol": row[5].strip(),
                                    "quantity": float(row[6].strip()),
                                    "price": float(row[8].strip().replace(",", "")),
                                }
                            )
                        except (ValueError, IndexError) as exc:
                            logger.warning("import_csv_positions: skipping row %s — %s", row, exc)
        except Exception as exc:
            logger.error("import_csv_positions read failed (%s): %s", csv_path, exc)
            return {
                "imported": 0,
                "skipped": 0,
                "total_in_db": 0,
                "fills_from_csv": 0,
                "error": str(exc),
            }

        if not statement_date:
            statement_date = "20260529"

        # Normalise to YYYY-MM-DD for fill_time
        if len(statement_date) == 8:
            fill_date = (
                f"{statement_date[:4]}-{statement_date[4:6]}-{statement_date[6:]}T00:00:00+00:00"
            )
        else:
            fill_date = f"{statement_date}T00:00:00+00:00"

        imported = 0
        skipped = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        if parsed:
            try:
                with closing(sqlite3.connect(self._db_path)) as conn:
                    for p in parsed:
                        exec_id = f"CSV_POS_{account}_{p['symbol']}_{statement_date}"
                        if conn.execute(
                            "SELECT 1 FROM ibkr_fills WHERE exec_id = ?", (exec_id,)
                        ).fetchone():
                            skipped += 1
                            continue
                        conn.execute(
                            """
                            INSERT INTO ibkr_fills
                                (exec_id, account, symbol, sec_type, expiry, side,
                                 quantity, price, avg_price, commission, exchange,
                                 currency, fill_time, order_id, imported_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                exec_id,
                                account,
                                p["symbol"],
                                "FUT",
                                "",
                                "BOT",
                                p["quantity"],
                                p["price"],
                                p["price"],
                                None,
                                None,
                                p["currency"],
                                fill_date,
                                None,
                                now_iso,
                            ),
                        )
                        imported += 1
                    conn.commit()
            except Exception as exc:
                logger.error("import_csv_positions DB write failed: %s", exc)

        total = 0
        try:
            with closing(sqlite3.connect(self._db_path)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM ibkr_fills").fetchone()
                total = row[0] if row else 0
        except Exception:
            pass

        return {
            "imported": imported,
            "skipped": skipped,
            "total_in_db": total,
            "fills_from_csv": len(parsed),
            "account": account,
            "statement_date": statement_date,
        }

    def _summary(
        self,
        fills: list[dict],
        imported: int,
        skipped: int,
        connected: bool = True,
    ) -> dict:
        total = 0
        try:
            with closing(sqlite3.connect(self._db_path)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM ibkr_fills").fetchone()
                total = row[0] if row else 0
        except Exception:
            pass
        return {
            "imported": imported,
            "skipped": skipped,
            "total_in_db": total,
            "fills_from_ib": len(fills),
            "connected": connected,
        }
