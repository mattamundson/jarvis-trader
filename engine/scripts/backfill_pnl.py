#!/usr/bin/env python3
"""
Sprint 17 US-1702 — Backfill NULL pnl for existing paper trades.
Run once from engine/: python scripts/backfill_pnl.py

Targets closed trades where pnl IS NULL and exit_price IS NOT NULL.
Uses contract multipliers so pnl reflects real dollar value per contract.
The column storing direction is 'side' (buy/sell/long/short/buy_to_open etc.).
"""

import sqlite3
from pathlib import Path

MULTIPLIERS = {
    "MCL": 100.0,
    "MNQ": 2.0,
    "MES": 5.0,
    "MGC": 10.0,
    "ES": 50.0,
}
DEFAULT = 1.0

db_path = Path(__file__).parent.parent / "data" / "jarvis_trader.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, symbol, side, entry_price, exit_price, quantity FROM paper_trades "
    "WHERE pnl IS NULL AND exit_price IS NOT NULL AND entry_price IS NOT NULL"
).fetchall()

updated = 0
for row in rows:
    mult = MULTIPLIERS.get(str(row["symbol"]).upper(), DEFAULT)
    qty = row["quantity"] or 1
    side_lower = str(row["side"]).lower()
    is_short = "sell" in side_lower or "short" in side_lower
    if not is_short:
        pnl = (float(row["exit_price"]) - float(row["entry_price"])) * qty * mult
    else:
        pnl = (float(row["entry_price"]) - float(row["exit_price"])) * qty * mult
    conn.execute("UPDATE paper_trades SET pnl = ? WHERE id = ?", (round(pnl, 4), row["id"]))
    updated += 1
    print(f"  Trade {row['id']}: {row['symbol']} {row['side']} pnl={pnl:.2f}")

conn.commit()
conn.close()
print(f"\nBackfilled {updated} trades.")
