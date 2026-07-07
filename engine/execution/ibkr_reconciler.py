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
                                 currency, fill_time, order_id, order_ref,
                                 parent_order_id, imported_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                fill.get("order_ref", ""),
                                fill.get("parent_order_id"),
                                now_iso,
                            ),
                        )
                        imported += 1
                    conn.commit()
            except Exception as exc:
                logger.error("IBKRReconciler DB write failed: %s", exc)

            # Write-side: persist entry slippage onto matched paper_trades rows.
            # Idempotent + resilient (no-op pre-migration-038); never breaks reconcile.
            symbols = {str(f.get("symbol", "")).upper() for f in fills if f.get("symbol")}
            for sym in symbols:
                try:
                    persist_entry_slippage(self._db_path, sym)
                except Exception as exc:
                    logger.warning("persist_entry_slippage(%s) failed: %s", sym, exc)

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

    def compare_fills_to_trades(
        self,
        symbol: str,
        match_window_sec: int = 3600,
    ) -> dict:
        """Compare reconciled real IB fills to paper_trades intent for ``symbol``.

        Thin instance wrapper around :func:`compare_fills_to_trades` so callers
        holding a reconciler can measure fidelity without knowing the db path.
        """
        return compare_fills_to_trades(self._db_path, symbol, match_window_sec)


# ── Side mapping & parsing helpers ──────────────────────────────────────────────

# paper_trades.side (intent) -> ibkr_fills.side (IB execution report) equivalence.
_TRADE_TO_FILL_SIDE = {"buy": "BOT", "sell": "SLD"}


def _parse_ts(value: Any) -> Optional[datetime]:
    """Lenient ISO timestamp parse. Accepts 'T' or space separators, optional tz.

    Real fill_time is ``str(execution.time)`` ("2026-06-02 14:30:00+00:00");
    paper_trades.entry_time is ISO. Returns a tz-aware UTC datetime or None.
    """
    if not value:
        return None
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compare_fills_to_trades(
    db_path: str | Path,
    symbol: str,
    match_window_sec: int = 3600,
) -> dict:
    """Measure execution fidelity: real JARVIS fills vs paper_trades intent.

    Only fills tagged with a ``JARVIS-`` orderRef are considered — the
    DUP662235 demo-seed activity (untagged) is filtered out and reported as
    ``n_demo_excluded``. Each intended paper_trades entry is matched to the
    nearest unconsumed JARVIS real fill of the corresponding side
    (buy↔BOT, sell↔SLD) within ``match_window_sec``; entry slippage is the
    signed (real_fill_price − intended_entry_price) in price points.

    Read-only and resilient: returns a structured dict even when the table or
    columns are absent (e.g. before migration 037), so callers never raise.
    The matching is a time-proximity heuristic — until paper_trades carries a
    stored order_ref join key, ``match_method`` documents the limitation.
    """
    sym = symbol.upper()
    result: dict[str, Any] = {
        "symbol": sym,
        "n_real_fills": 0,
        "n_demo_excluded": 0,
        "n_paper_trades": 0,
        "n_matched": 0,
        "n_unmatched_trades": 0,
        "n_unmatched_fills": 0,
        "avg_abs_slippage_pts": None,
        "max_abs_slippage_pts": None,
        "match_window_sec": match_window_sec,
        "match_method": "side+nearest-time (no stored order_ref join key yet)",
        "matches": [],
    }

    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            # JARVIS-tagged real fills only.
            real_fills = conn.execute(
                """
                SELECT side, price, fill_time, order_ref
                FROM   ibkr_fills
                WHERE  UPPER(symbol) = ? AND order_ref LIKE 'JARVIS-%'
                ORDER  BY fill_time ASC
                """,
                (sym,),
            ).fetchall()
            demo_row = conn.execute(
                """
                SELECT COUNT(*) FROM ibkr_fills
                WHERE  UPPER(symbol) = ?
                  AND  (order_ref IS NULL OR order_ref NOT LIKE 'JARVIS-%')
                """,
                (sym,),
            ).fetchone()
            trades = conn.execute(
                """
                SELECT side, entry_price, entry_time
                FROM   paper_trades
                WHERE  UPPER(symbol) = ? AND entry_price IS NOT NULL
                ORDER  BY entry_time ASC
                """,
                (sym,),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        # Missing table/column (pre-migration) — return the empty scaffold.
        logger.debug("compare_fills_to_trades: %s", exc)
        return result
    except Exception as exc:
        logger.warning("compare_fills_to_trades failed: %s", exc)
        return result

    result["n_real_fills"] = len(real_fills)
    result["n_demo_excluded"] = int(demo_row[0]) if demo_row else 0
    result["n_paper_trades"] = len(trades)

    # Greedy nearest-time matching, each real fill consumed at most once.
    consumed: set[int] = set()
    slippages: list[float] = []
    for tr in trades:
        want_side = _TRADE_TO_FILL_SIDE.get(str(tr["side"]).lower())
        t_ts = _parse_ts(tr["entry_time"])
        if want_side is None or t_ts is None:
            continue
        best_idx: Optional[int] = None
        best_gap: Optional[float] = None
        for i, fl in enumerate(real_fills):
            if i in consumed or str(fl["side"]).upper() != want_side:
                continue
            f_ts = _parse_ts(fl["fill_time"])
            if f_ts is None:
                continue
            gap = abs((f_ts - t_ts).total_seconds())
            if gap > match_window_sec:
                continue
            if best_gap is None or gap < best_gap:
                best_gap, best_idx = gap, i
        if best_idx is None:
            continue
        consumed.add(best_idx)
        fill = real_fills[best_idx]
        try:
            slip = float(fill["price"]) - float(tr["entry_price"])
        except (TypeError, ValueError):
            continue
        slippages.append(abs(slip))
        result["matches"].append(
            {
                "side": str(tr["side"]).lower(),
                "intended_entry_price": float(tr["entry_price"]),
                "real_fill_price": float(fill["price"]),
                "slippage_pts": round(slip, 6),
                "trade_entry_time": tr["entry_time"],
                "fill_time": fill["fill_time"],
                "order_ref": fill["order_ref"],
                "gap_sec": round(best_gap, 1) if best_gap is not None else None,
            }
        )

    result["n_matched"] = len(result["matches"])
    result["n_unmatched_trades"] = result["n_paper_trades"] - result["n_matched"]
    result["n_unmatched_fills"] = result["n_real_fills"] - len(consumed)
    if slippages:
        result["avg_abs_slippage_pts"] = round(sum(slippages) / len(slippages), 6)
        result["max_abs_slippage_pts"] = round(max(slippages), 6)
    return result


def persist_entry_slippage(
    db_path: str | Path,
    symbol: str,
    match_window_sec: int = 3600,
) -> dict:
    """Write-side counterpart to compare_fills_to_trades: persist entry slippage
    (in ticks) onto matched paper_trades rows (paper_trades.slippage_ticks,
    migration 038).

    Uses the same side+nearest-time matching as compare_fills_to_trades but
    carries the paper_trades row id so the signed entry slippage can be written
    back. ``slippage_ticks = (real_fill_price - intended_entry_price) /
    tick_size`` (signed, REAL; tick_size from contract_specs).

    Invoked after reconcile() imports fills — the only point at which fresh real
    fills exist. Idempotent: re-running recomputes and overwrites slippage_ticks
    for matched rows (unmatched rows are left untouched / NULL). Resilient:
    returns ``{"n_persisted": 0, ...}`` and never raises if the column/table is
    absent (pre-migration-038) or the symbol has no contract spec.
    """
    sym = symbol.upper()
    result: dict[str, Any] = {"symbol": sym, "n_matched": 0, "n_persisted": 0}

    try:
        from backtest.contract_specs import get_spec

        tick_size = float(get_spec(sym).tick_size)
    except Exception as exc:
        logger.debug("persist_entry_slippage: no contract spec for %s: %s", sym, exc)
        result["skipped"] = f"no contract spec for {sym}"
        return result
    if tick_size <= 0:
        result["skipped"] = "non-positive tick_size"
        return result

    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.row_factory = sqlite3.Row
            real_fills = conn.execute(
                """
                SELECT side, price, fill_time
                FROM   ibkr_fills
                WHERE  UPPER(symbol) = ? AND order_ref LIKE 'JARVIS-%'
                ORDER  BY fill_time ASC
                """,
                (sym,),
            ).fetchall()
            trades = conn.execute(
                """
                SELECT id, side, entry_price, entry_time
                FROM   paper_trades
                WHERE  UPPER(symbol) = ? AND entry_price IS NOT NULL
                ORDER  BY entry_time ASC
                """,
                (sym,),
            ).fetchall()

            consumed: set[int] = set()
            updates: list[tuple[float, int]] = []
            for tr in trades:
                want_side = _TRADE_TO_FILL_SIDE.get(str(tr["side"]).lower())
                t_ts = _parse_ts(tr["entry_time"])
                if want_side is None or t_ts is None:
                    continue
                best_idx: Optional[int] = None
                best_gap: Optional[float] = None
                for i, fl in enumerate(real_fills):
                    if i in consumed or str(fl["side"]).upper() != want_side:
                        continue
                    f_ts = _parse_ts(fl["fill_time"])
                    if f_ts is None:
                        continue
                    gap = abs((f_ts - t_ts).total_seconds())
                    if gap > match_window_sec:
                        continue
                    if best_gap is None or gap < best_gap:
                        best_gap, best_idx = gap, i
                if best_idx is None:
                    continue
                consumed.add(best_idx)
                fill = real_fills[best_idx]
                try:
                    slip_pts = float(fill["price"]) - float(tr["entry_price"])
                except (TypeError, ValueError):
                    continue
                updates.append((round(slip_pts / tick_size, 4), int(tr["id"])))

            result["n_matched"] = len(updates)
            for slip_ticks, trade_id in updates:
                conn.execute(
                    "UPDATE paper_trades SET slippage_ticks = ? WHERE id = ?",
                    (slip_ticks, trade_id),
                )
            conn.commit()
            result["n_persisted"] = len(updates)
    except sqlite3.OperationalError as exc:
        # Missing slippage_ticks column/table (pre-migration-038) — no-op.
        logger.debug("persist_entry_slippage: %s", exc)
        return result
    except Exception as exc:
        logger.warning("persist_entry_slippage failed: %s", exc)
        return result

    if result["n_persisted"]:
        logger.info(
            "persist_entry_slippage: %s — wrote slippage_ticks to %d paper_trades rows",
            sym,
            result["n_persisted"],
        )
    return result
