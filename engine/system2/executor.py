"""
System 2 — Main Executor
========================
Wires System2SignalMonitor + System2OrderManager + IBKRExecutor into a
single async run loop for live paper trading of ES/NQ extended-hours setups.

Usage:
    python -m engine.system2.executor --paper
    python -m engine.system2.executor --paper --dry-run
    python -m engine.system2.executor --help

The executor:
  1. Connects to IBKR paper account DUP662235 on port 4002
  2. Starts the signal monitor (ES + NQ, 1h bars, extended hours filter)
  3. On each signal: sizes position, submits bracket orders via IBKRExecutor
  4. On each bar close: advances state machines (backstop/T1/T2 tracking)
  5. Writes trade log to engine/system2/logs/system2_trades.jsonl
  6. Graceful shutdown on SIGINT/SIGTERM

Safety:
  - All orders route through SafetyLayer (existing invariants unchanged)
  - LIVE_TRADING_ENABLED = False by default — must be explicitly overridden
  - Paper mode forced unless --live flag provided (not recommended)
  - MAX_SINGLE_ORDER_VALUE_USD = 5000, MAX_DAILY_LOSS_PCT = 2%
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Path setup ────────────────────────────────────────────────────────────────
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ENGINE_ROOT))

from system2.signal_monitor    import System2SignalMonitor, System2Signal
from system2.order_manager     import System2OrderManager, PositionRecord
from system2.kill_switch       import KillSwitch, PositionReconciler, DeadMansSwitch
from system2.portfolio_allocator import PortfolioAllocator
try:
    from system2.fill_callbacks import wire_fill_callbacks
    _FILL_CALLBACKS_AVAILABLE = True
except ImportError:
    _FILL_CALLBACKS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── Logging setup ─────────────────────────────────────────────────────────────
def _setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt)
    # Silence noisy third-party loggers
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)


# ── Trade log ─────────────────────────────────────────────────────────────────
_LOG_DIR = _ENGINE_ROOT / "system2" / "logs"

def _log_signal(sig: System2Signal):
    """Append signal event to JSONL trade log."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": "SIGNAL",
        "ts":    datetime.now(timezone.utc).isoformat(),
        "symbol":       sig.symbol,
        "entry_price":  sig.entry_price,
        "stop_price":   sig.stop_price,
        "t1_price":     sig.t1_price,
        "t2_price":     sig.t2_price,
        "atr":          sig.atr,
        "bar_time":     sig.bar_time.isoformat(),
        "stage1_bar":   sig.stage1_bar.isoformat() if sig.stage1_bar else None,
        "stage2_bar":   sig.stage2_bar.isoformat() if sig.stage2_bar else None,
        "stage3_bar":   sig.stage3_bar.isoformat() if sig.stage3_bar else None,
    }
    with open(_LOG_DIR / "system2_trades.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")

def _log_closed(pos: PositionRecord):
    """Append position close event to JSONL trade log."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "event":          "CLOSE",
        "ts":             datetime.now(timezone.utc).isoformat(),
        "symbol":         pos.symbol,
        "entry_price":    pos.entry_price,
        "stop_price":     pos.stop_price,
        "t1_price":       pos.t1_price,
        "t2_price":       pos.t2_price,
        "total_contracts": pos.total_contracts,
        "bars_open":      pos.bars_open,
        "t1_hit":         pos.t1_hit,
        "t2_hit":         pos.t2_hit,
        "close_reason":   pos.close_reason,
        "closed_at":      pos.closed_at.isoformat() if pos.closed_at else None,
        "pnl_usd":        pos.pnl_usd,
    }
    with open(_LOG_DIR / "system2_trades.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── IBKR connection helpers ───────────────────────────────────────────────────
def _build_ibkr_executor(paper: bool = True):
    """
    Attempt to instantiate IBKRExecutor with minimal settings.
    Returns None if ib_async is not installed or gateway is not reachable —
    the order manager handles None gracefully (dry run mode).
    """
    try:
        from execution.ibkr_executor import IBKRExecutor
        from risk.safety_layer import SafetyLayer
    except Exception as e:
        logger.warning(f"Could not import IBKR executor: {e} — running in dry-run mode")
        return None

    class _Settings:
        """Minimal settings shim for IBKRExecutor."""
        IBKR_HOST          = "127.0.0.1"
        IBKR_PORT          = 4002 if paper else 4001
        IBKR_CLIENT_ID     = 10  # distinct from Strategy C+ (client 1)
        LIVE_TRADING_ENABLED   = False  # paper only
        REQUIRE_HUMAN_APPROVAL = False  # automated execution
        MAX_SINGLE_ORDER_VALUE_USD = 5000.0
        MAX_DAILY_LOSS_PCT   = 0.02
        MAX_DRAWDOWN_PCT     = 0.10
        # Futures margin table used by SafetyLayer
        FUTURES_MARGIN_OVERRIDE: dict = {}

    settings = _Settings()

    try:
        safety = SafetyLayer(config=settings)
        executor = IBKRExecutor(settings=settings, safety_layer=safety)
        return executor
    except Exception as e:
        logger.warning(f"IBKRExecutor init failed: {e} — running in dry-run mode")
        return None


# ── Main executor class ───────────────────────────────────────────────────────
class System2Executor:
    """
    Top-level orchestrator for System 2 live paper trading.

    Lifecycle:
      start() → connects IBKR, starts monitor + bar-advance loop
      stop()  → graceful shutdown (cancel working orders, disconnect)
    """

    PAPER_ACCOUNT  = "DUP662235"
    PAPER_PORT     = 4002
    BAR_ADVANCE_INTERVAL = 65  # seconds — poll for new bar slightly after bar close

    def __init__(
        self,
        paper: bool = True,
        dry_run: bool = False,
        poll_interval: int = 60,
        debug: bool = False,
    ):
        self.paper        = paper
        self.dry_run      = dry_run
        self.poll_interval = poll_interval
        self._running     = False

        # Build IBKR executor (None = dry run)
        self._ibkr = None if dry_run else _build_ibkr_executor(paper=paper)

        # Safety + allocation
        self._kill_switch = KillSwitch()
        self._dead_mans   = DeadMansSwitch(ibkr_port=self.PAPER_PORT if paper else 4001)

        # Order manager
        self._order_mgr = System2OrderManager(
            ibkr_executor      = self._ibkr,
            paper              = paper,
            on_position_closed = self._on_position_closed,
        )

        # Portfolio allocator
        self._allocator = PortfolioAllocator(
            ibkr_executor = self._ibkr,
            order_manager = self._order_mgr,
            account_size  = 50_000.0,
        )

        # Signal monitor
        self._monitor = System2SignalMonitor(
            on_signal       = self._on_signal,
            symbols         = ["ES", "NQ"],
            poll_interval   = poll_interval,
            compression_window = 6,
            dry_run         = dry_run,
        )

    async def start(self):
        """Connect IBKR and start the monitoring loop."""
        logger.info(
            f"[System2Executor] Starting | paper={self.paper} "
            f"dry_run={self.dry_run} account={self.PAPER_ACCOUNT}"
        )

        # Connect to IBKR Gateway
        if self._ibkr is not None:
            connected = await self._ibkr.connect()
            if not connected:
                logger.error(
                    "Could not connect to IBKR Gateway. "
                    "Ensure IB Gateway is running on port 4002. "
                    "Falling back to dry-run mode."
                )
                self._ibkr = None
                self._order_mgr.ibkr = None
            else:
                acct = self.PAPER_ACCOUNT
                logger.info(f"[System2Executor] IBKR connected — account {acct}")
        else:
            logger.info("[System2Executor] No IBKR connection — DRY RUN mode")

        # Position reconciliation before accepting any signals
        if self._ibkr is not None:
            reconciler = PositionReconciler(
                order_manager   = self._order_mgr,
                ibkr_executor   = self._ibkr,
                flatten_orphans = False,  # conservative: log only, don't auto-flatten
            )
            report = await reconciler.reconcile()
            logger.info("[System2Executor] Reconciliation: %s", report["status"])
            if report["discrepancies"]:
                logger.warning(
                    "[System2Executor] %d discrepancies found — review reconcile_log.jsonl",
                    len(report["discrepancies"])
                )

        # Wire real-time fill callbacks to ib_async events
        if self._ibkr is not None and _FILL_CALLBACKS_AVAILABLE:
            try:
                ib_instance = getattr(self._ibkr, '_ib', None)
                if ib_instance is not None:
                    wire_fill_callbacks(ib_instance, self._order_mgr)
                    logger.info("[System2Executor] Fill callbacks wired")
            except Exception as e:
                logger.warning("[System2Executor] Fill callback wire failed: %s", e)

        self._running = True

        # Run signal monitor + bar advance loop + heartbeat concurrently
        await asyncio.gather(
            self._monitor.run(),
            self._bar_advance_loop(),
            self._dead_mans.beat_loop(),
        )

    async def stop(self):
        """Graceful shutdown."""
        logger.info("[System2Executor] Shutdown initiated")
        self._running = False
        self._monitor.stop()

        # Cancel all working orders and flatten if IBKR connected
        if self._ibkr is not None:
            try:
                cancelled = await self._ibkr.cancel_all_orders()
                logger.info(f"[System2Executor] Cancelled {cancelled} working orders")
            except Exception as e:
                logger.error(f"Cancel all orders failed: {e}")

            try:
                await self._ibkr.disconnect()
                logger.info("[System2Executor] IBKR disconnected")
            except Exception as e:
                logger.error(f"IBKR disconnect failed: {e}")

        logger.info("[System2Executor] Shutdown complete")

    # ── Signal callback ───────────────────────────────────────────────────────
    async def _on_signal(self, sig: System2Signal):
        """Called by signal monitor when a setup completes."""
        logger.info(f"[System2Executor] Signal received: {sig.summary()}")
        _log_signal(sig)

        # Portfolio allocation check before submitting
        # Use 1 contract for the cap check — order manager sizes by 1% risk
        # which always yields 1 contract for ES/NQ on a $50k account.
        # Passing 2 (old estimate) was incorrectly blocking every signal.
        check = await self._allocator.check_new_order(
            symbol        = sig.symbol,
            contracts     = 1,
            side          = sig.direction,
            current_price = sig.entry_price,
        )
        if not check.approved:
            logger.warning(
                f"[System2Executor] Signal BLOCKED by allocator: {check.reason}"
            )
            return

        pos = await self._order_mgr.on_signal(sig)
        if pos:
            logger.info(
                f"[System2Executor] Position opened: {pos.symbol} "
                f"{pos.total_contracts}ct @ {pos.entry_price:.2f}"
            )

    # ── Position close callback ───────────────────────────────────────────────
    async def _on_position_closed(self, pos: PositionRecord):
        """Called by order manager when a position closes."""
        _log_closed(pos)
        logger.info(
            f"[System2Executor] Position closed: {pos.symbol} | "
            f"reason={pos.close_reason} | pnl=${pos.pnl_usd:.2f}"
        )

    # ── Bar advance loop ──────────────────────────────────────────────────────
    async def _bar_advance_loop(self):
        """
        Periodically fetch the latest bar for active positions and advance
        the state machine (backstop check, T1/T2 fill tracking).

        This is a fallback mechanism — in production IBKR sends real-time
        fills via ib_async callbacks. For paper/dry-run this simulates bar checks.
        """
        import yfinance as yf
        import pandas as pd

        _YF_MAP = {"ES": "ES=F", "NQ": "NQ=F"}

        while self._running:
            await asyncio.sleep(self.BAR_ADVANCE_INTERVAL)
            active = self._order_mgr.active_positions()
            if not active:
                continue

            for sym, pos in active.items():
                try:
                    ticker = _YF_MAP.get(sym, f"{sym}=F")
                    raw = yf.download(ticker, period="2d", interval="1h",
                                      progress=False, auto_adjust=True)
                    if raw.empty:
                        continue

                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = raw.columns.get_level_values(0)
                    raw.columns = [c.lower() for c in raw.columns]

                    latest = raw.iloc[-1]
                    bar = {
                        "high":      float(latest["high"]),
                        "low":       float(latest["low"]),
                        "close":     float(latest["close"]),
                        "timestamp": raw.index[-1].to_pydatetime(),
                    }
                    await self._order_mgr.on_bar(sym, bar)

                except Exception as e:
                    logger.error(f"[{sym}] Bar advance error: {e}", exc_info=True)

    # ── Status ────────────────────────────────────────────────────────────────
    def status(self) -> str:
        running_str = "RUNNING" if self._running else "STOPPED"
        ibkr_str    = "CONNECTED" if self._ibkr else "DRY RUN"
        positions   = self._order_mgr.position_summary()
        return (
            f"System2Executor: {running_str} | IBKR: {ibkr_str} | "
            f"paper={self.paper}\nPositions:\n{positions}"
        )


# ── CLI entry point ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="System 2 — ES/NQ Extended-Hours IBKR Executor"
    )
    parser.add_argument(
        "--paper", action="store_true", default=True,
        help="Use paper trading account DUP662235 on port 4002 (default: True)"
    )
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="WARNING: Use live account on port 4001. Requires LIVE_TRADING_ENABLED override."
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Detect signals and log without submitting any orders"
    )
    parser.add_argument(
        "--poll", type=int, default=60,
        help="Bar poll interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--debug", action="store_true", default=False,
        help="Enable debug logging"
    )
    args = parser.parse_args()

    _setup_logging(debug=args.debug)

    paper = not args.live
    if args.live:
        logger.warning(
            "LIVE MODE requested. This will submit real orders. "
            "Safety layer will still enforce LIVE_TRADING_ENABLED=False. "
            "You must override this in settings to actually trade live."
        )

    executor = System2Executor(
        paper        = paper,
        dry_run      = args.dry_run,
        poll_interval = args.poll,
        debug        = args.debug,
    )

    # Handle graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(signum, frame):
        logger.info(f"Signal {signum} received — shutting down")
        loop.create_task(executor.stop())

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(executor.start())
    except KeyboardInterrupt:
        loop.run_until_complete(executor.stop())
    finally:
        loop.close()
        logger.info("[System2Executor] Process exited")


if __name__ == "__main__":
    main()
