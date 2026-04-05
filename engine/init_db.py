#!/usr/bin/env python3
"""
JARVIS TRADER — Database Initialization Script
Run this once to set up the SQLite database, or to reset/migrate it.
Usage: python init_db.py [--reset] [--db-path PATH]
"""

import argparse
import os
import shutil
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Initialize JARVIS TRADER database")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all tables (WARNING: deletes all data)",
    )
    parser.add_argument(
        "--db-path", default="data/jarvis_trader.db", help="Path to SQLite database file"
    )
    args = parser.parse_args()

    # Create data directory
    os.makedirs(
        os.path.dirname(args.db_path) if os.path.dirname(args.db_path) else "data", exist_ok=True
    )

    if args.reset and os.path.exists(args.db_path):
        # Backup before reset
        backup_path = f"{args.db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(args.db_path, backup_path)
        print(f"Backup created: {backup_path}")
        os.remove(args.db_path)
        print(f"Removed existing database: {args.db_path}")

    from database.schema import DatabaseManager

    db = DatabaseManager(db_path=args.db_path)
    db.initialize()

    print(f"Database initialized at: {os.path.abspath(args.db_path)}")
    print(
        "Tables created: paper_trades, positions, decisions, daily_pnl, settings, system_state, schema_version"
    )


if __name__ == "__main__":
    main()
