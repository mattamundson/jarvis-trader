"""
JARVIS TRADER — Synthetic Paper Trade Seeder
=============================================
Seeds the SQLite database with realistic synthetic paper trades over the
last 30 trading days so that the performance analytics, scorecard, and
P&L charts display meaningful data instead of zeros.

Usage (run from engine/ directory):
    cd engine
    python ../scripts/seed_paper_trades.py

Or from project root:
    python scripts/seed_paper_trades.py
    (will auto-locate engine/ and data/ directories relative to this file)

Parameters
----------
- 30 trading days (Mon-Fri, skip weekends)
- 2-4 trades per day
- Win rate: ~65%
- Average win: ~$50  (1 MES contract, 10-point move × $5)
- Average loss: ~$30 (1 MES contract,  6-point move × $5)
- Symbols: MES (primary), occasional MNQ
- Base price: MES ~5000 ± 200, MNQ ~18000 ± 500

Guard: skips seeding if the database already contains > 10 trades.
"""

from __future__ import annotations

import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — make sure engine/ is importable regardless of cwd
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent          # .../jarvis-trader/scripts/
PROJECT_ROOT = SCRIPT_DIR.parent                       # .../jarvis-trader/
ENGINE_ROOT = PROJECT_ROOT / "engine"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# ---------------------------------------------------------------------------
# Import DatabaseManager directly from database/schema.py, bypassing the
# package __init__.py which pulls in asyncpg (not needed here).
# ---------------------------------------------------------------------------
import importlib.util as _ilu
import types as _types

_schema_path = ENGINE_ROOT / "database" / "schema.py"

# We need database.migrations to be importable too (schema imports it).
# Pre-register a stub for the database package so Python does not try to
# execute database/__init__.py (which requires asyncpg).
if "database" not in sys.modules:
    _pkg = _types.ModuleType("database")
    _pkg.__path__ = [str(ENGINE_ROOT / "database")]  # type: ignore[attr-defined]
    _pkg.__package__ = "database"
    sys.modules["database"] = _pkg

_spec = _ilu.spec_from_file_location("database.schema", _schema_path)
_mod  = _ilu.module_from_spec(_spec)          # type: ignore[arg-type]
sys.modules["database.schema"] = _mod
_spec.loader.exec_module(_mod)               # type: ignore[union-attr]

DatabaseManager = _mod.DatabaseManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = ENGINE_ROOT / "data" / "jarvis_trader.db"

TRADING_DAYS_TO_GENERATE = 30
MIN_TRADES_PER_DAY = 2
MAX_TRADES_PER_DAY = 4

WIN_RATE = 0.65           # 65% of trades are winners

# MES parameters
MES_BASE_PRICE = 5000.0
MES_TICK_VALUE = 5.0      # $5 per point

# Average win/loss in POINTS (pnl = points × tick_value × qty)
WIN_POINTS_MU    = 10.0   # avg win  ≈ $50
WIN_POINTS_SIGMA =  3.0
LOSS_POINTS_MU   =  6.0   # avg loss ≈ $30
LOSS_POINTS_SIGMA = 2.0

# MNQ parameters
MNQ_BASE_PRICE  = 18000.0
MNQ_TICK_VALUE  = 2.0     # $2 per point
MNQ_WIN_POINTS_MU    = 25.0
MNQ_WIN_POINTS_SIGMA =  8.0
MNQ_LOSS_POINTS_MU   = 15.0
MNQ_LOSS_POINTS_SIGMA = 5.0

STARTING_BALANCE = 10_000.0   # simulated paper account balance


# ---------------------------------------------------------------------------
# Helper: generate trading days
# ---------------------------------------------------------------------------

def get_trading_days(n: int = 30) -> list[datetime]:
    """Return the last *n* Mon-Fri days in UTC, oldest first."""
    days: list[datetime] = []
    d = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:   # 0=Mon … 4=Fri
            days.append(d)
    return list(reversed(days))


# ---------------------------------------------------------------------------
# Helper: drift the underlying price slowly over 30 days
# ---------------------------------------------------------------------------

def build_price_series(base: float, n_days: int, drift_sigma: float = 50.0) -> list[float]:
    """Random-walk price series with a slight upward bias."""
    prices = [base]
    for _ in range(n_days - 1):
        change = random.gauss(0.5, drift_sigma)   # slight positive drift
        prices.append(max(base * 0.85, prices[-1] + change))
    return prices


# ---------------------------------------------------------------------------
# Core seeding function
# ---------------------------------------------------------------------------

def seed(db: DatabaseManager) -> None:
    """Generate and insert synthetic trades + daily P&L snapshots."""

    # ---- Guard: don't double-seed ----------------------------------------
    existing = db.get_trade_history(limit=11)
    if len(existing) > 10:
        print(f"Database already has {len(existing)} trades — skipping seed.")
        print("Delete the database or trades manually to re-seed.")
        return

    trading_days = get_trading_days(TRADING_DAYS_TO_GENERATE)
    mes_prices   = build_price_series(MES_BASE_PRICE,  len(trading_days), drift_sigma=40.0)
    mnq_prices   = build_price_series(MNQ_BASE_PRICE,  len(trading_days), drift_sigma=150.0)

    rng = random.Random(42)   # deterministic seed for reproducibility

    total_trades  = 0
    total_wins    = 0
    total_losses  = 0
    cumulative_pnl = 0.0
    balance        = STARTING_BALANCE

    print(f"\nSeeding {TRADING_DAYS_TO_GENERATE} trading days of synthetic paper trades...")
    print("-" * 60)

    for day_idx, trade_day in enumerate(trading_days):
        day_str      = trade_day.strftime("%Y-%m-%d")
        mes_price    = mes_prices[day_idx]
        mnq_price    = mnq_prices[day_idx]

        n_trades     = rng.randint(MIN_TRADES_PER_DAY, MAX_TRADES_PER_DAY)
        day_pnl      = 0.0
        day_wins     = 0
        day_losses   = 0
        day_start_balance = balance

        # Spread trades evenly through the 9:30–15:30 ET window
        # (stored as UTC: 13:30–19:30)
        session_open_utc  = trade_day.replace(hour=13, minute=30)
        session_close_utc = trade_day.replace(hour=19, minute=30)
        session_minutes   = int((session_close_utc - session_open_utc).total_seconds() / 60)

        # Evenly space entry times, then add a short hold (5-45 min)
        entry_offsets = sorted(rng.sample(range(10, session_minutes - 60), min(n_trades, session_minutes - 70)))

        for offset_min in entry_offsets:
            # Pick symbol: 80% MES, 20% MNQ
            use_mnq = (rng.random() < 0.20)
            if use_mnq:
                symbol     = "MNQ"
                base_price = mnq_price
                tick_val   = MNQ_TICK_VALUE
                win_mu     = MNQ_WIN_POINTS_MU
                win_sigma  = MNQ_WIN_POINTS_SIGMA
                loss_mu    = MNQ_LOSS_POINTS_MU
                loss_sigma = MNQ_LOSS_POINTS_SIGMA
            else:
                symbol     = "MES"
                base_price = mes_price
                tick_val   = MES_TICK_VALUE
                win_mu     = WIN_POINTS_MU
                win_sigma  = WIN_POINTS_SIGMA
                loss_mu    = LOSS_POINTS_MU
                loss_sigma = LOSS_POINTS_SIGMA

            # Add intraday noise to the base price
            entry_price = round(base_price + rng.gauss(0, base_price * 0.002), 2)

            # Randomly go long or short
            side = rng.choice(["buy", "sell"])
            qty  = 1.0

            # Determine win/loss
            is_win = (rng.random() < WIN_RATE)

            if is_win:
                move_points = abs(rng.gauss(win_mu, win_sigma))
                exit_price  = (entry_price + move_points) if side == "buy" else (entry_price - move_points)
                raw_pnl     = move_points * tick_val * qty
            else:
                move_points = abs(rng.gauss(loss_mu, loss_sigma))
                exit_price  = (entry_price - move_points) if side == "buy" else (entry_price + move_points)
                raw_pnl     = -(move_points * tick_val * qty)

            raw_pnl     = round(raw_pnl, 2)
            exit_price  = round(exit_price, 2)

            # Build ISO-8601 timestamps
            entry_dt = session_open_utc + timedelta(minutes=offset_min)
            hold_min = rng.randint(5, 45)
            exit_dt  = entry_dt + timedelta(minutes=hold_min)
            # Clamp to session close
            if exit_dt > session_close_utc:
                exit_dt = session_close_utc - timedelta(minutes=1)

            entry_time_str = entry_dt.strftime("%Y-%m-%dT%H:%M:%S")
            exit_time_str  = exit_dt.strftime("%Y-%m-%dT%H:%M:%S")

            trade_id = str(uuid.uuid4())

            # Insert open trade
            db.insert_paper_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                quantity=qty,
                entry_price=entry_price,
                entry_time=entry_time_str,
                strategy_params={"seed": "synthetic", "day": day_str},
            )

            # Close the trade immediately (all synthetic trades are completed)
            db.close_paper_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=exit_time_str,
                pnl=raw_pnl,
            )

            day_pnl     += raw_pnl
            total_trades += 1
            if is_win:
                day_wins  += 1
                total_wins += 1
            else:
                day_losses  += 1
                total_losses += 1

        # ------------------------------------------------------------------
        # Compute day metrics and upsert daily_pnl snapshot
        # ------------------------------------------------------------------
        cumulative_pnl += day_pnl
        balance         = STARTING_BALANCE + cumulative_pnl

        # Simple drawdown: difference between start and end of this day
        day_dd = min(0.0, day_pnl)

        db.upsert_daily_pnl(
            date=day_str,
            starting_balance=round(day_start_balance, 2),
            ending_balance=round(balance, 2),
            realized_pnl=round(day_pnl, 2),
            unrealized_pnl=0.0,
            total_trades=n_trades,
            winning_trades=day_wins,
            losing_trades=day_losses,
            max_drawdown=round(day_dd, 2),
        )

        sign = "+" if day_pnl >= 0 else ""
        print(
            f"  {day_str}  trades={n_trades}  "
            f"W={day_wins} L={day_losses}  "
            f"day P&L={sign}{day_pnl:7.2f}  "
            f"balance={balance:,.2f}"
        )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    actual_win_rate = total_wins / total_trades if total_trades else 0.0
    print("\n" + "=" * 60)
    print("SEED COMPLETE")
    print("=" * 60)
    print(f"  Total trades    : {total_trades}")
    print(f"  Winning trades  : {total_wins}")
    print(f"  Losing  trades  : {total_losses}")
    print(f"  Actual win rate : {actual_win_rate:.1%}")
    print(f"  Total P&L       : ${cumulative_pnl:+,.2f}")
    print(f"  Ending balance  : ${balance:,.2f}")
    print(f"  Daily snapshots : {len(trading_days)}")
    print("=" * 60)
    print(f"\nDatabase: {DB_PATH}")
    print("Analytics, scorecard, and P&L charts should now show real data.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"JARVIS TRADER — Synthetic Paper Trade Seeder")
    print(f"Engine root : {ENGINE_ROOT}")
    print(f"Database    : {DB_PATH}")

    db_manager = DatabaseManager(db_path=str(DB_PATH))
    db_manager.initialize()

    seed(db_manager)
