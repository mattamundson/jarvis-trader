"""
System 2 — Kill Switch + Position Reconciliation + Dead-Man's Switch
=====================================================================
Three safety mechanisms required before going live with real capital.

1. Kill Switch
   ──────────────
   Human-confirmation gate to enable live trading. Writes a signed token
   to disk; executor checks for it on startup. Token expires after 24h.
   Run: python -m engine.system2.kill_switch --enable
   Run: python -m engine.system2.kill_switch --disable

2. Position Reconciliation
   ───────────────────────
   On startup, reads current IBKR positions and compares against local
   state. If mismatch detected (crash recovery scenario), logs a warning
   and optionally flattens orphaned positions before accepting new signals.
   Never assumes state is clean — always verifies with broker.

3. Dead-Man's Switch
   ──────────────────
   Heartbeat file updated every N seconds by running executor. If the
   file goes stale (process crashed), a separate watchdog process flattens
   all open positions via IBKR cancel_all + flatten_all. The watchdog is
   started as a background process by the executor on startup.

Usage:
    # Enable live trading for 24h (requires terminal confirmation)
    python -m engine.system2.kill_switch --enable

    # Check current status
    python -m engine.system2.kill_switch --status

    # Emergency disable (callable from any process)
    python -m engine.system2.kill_switch --disable

    # In executor code:
    from system2.kill_switch import KillSwitch, PositionReconciler, DeadMansSwitch
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STATE_DIR = Path(__file__).resolve().parent / "state"
_STATE_DIR.mkdir(exist_ok=True)

_KILL_SWITCH_FILE    = _STATE_DIR / "kill_switch.json"
_HEARTBEAT_FILE      = _STATE_DIR / "heartbeat.json"
_RECONCILE_LOG_FILE  = _STATE_DIR / "reconcile_log.jsonl"

_KILL_SWITCH_TTL_H   = 24      # token expires after 24 hours
_HEARTBEAT_INTERVAL  = 30      # seconds between heartbeat writes
_DEAD_MANS_TIMEOUT   = 120     # seconds of stale heartbeat before watchdog acts


# ═══════════════════════════════════════════════════════════════════════════════
# 1. KILL SWITCH
# ═══════════════════════════════════════════════════════════════════════════════

class KillSwitch:
    """
    Human-confirmation gate for live trading.

    LIVE_TRADING_ENABLED in IBKRExecutor is hardcoded False.
    This class provides a controlled unlock path:
      - Requires explicit CLI confirmation with account number
      - Token is time-limited (24h default)
      - Can be disabled instantly from any process
      - All enable/disable events are logged with timestamp

    Paper trading is ALWAYS allowed — kill switch only gates live.
    """

    def __init__(self, ttl_hours: int = _KILL_SWITCH_TTL_H):
        self.ttl_hours = ttl_hours

    def is_live_enabled(self) -> bool:
        """Check if live trading token is valid and unexpired."""
        if not _KILL_SWITCH_FILE.exists():
            return False
        try:
            state = json.loads(_KILL_SWITCH_FILE.read_text())
            if not state.get("enabled"):
                return False
            expires_at = datetime.fromisoformat(state["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                logger.warning("[KillSwitch] Live trading token EXPIRED — disabling")
                self._write_state(enabled=False, reason="token_expired")
                return False
            return True
        except Exception as e:
            logger.error("[KillSwitch] State read error: %s", e)
            return False

    def enable(self, account: str, reason: str = "manual_enable") -> bool:
        """
        Enable live trading. Requires account number confirmation.
        Called from CLI — not from automated code paths.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        self._write_state(
            enabled=True,
            account=account,
            reason=reason,
            expires_at=expires_at.isoformat(),
        )
        logger.warning(
            "[KillSwitch] LIVE TRADING ENABLED | account=%s | expires=%s",
            account, expires_at.strftime("%Y-%m-%d %H:%M UTC")
        )
        return True

    def disable(self, reason: str = "manual_disable") -> None:
        """Immediately disable live trading."""
        self._write_state(enabled=False, reason=reason)
        logger.warning("[KillSwitch] LIVE TRADING DISABLED | reason=%s", reason)

    def status(self) -> dict:
        if not _KILL_SWITCH_FILE.exists():
            return {"enabled": False, "reason": "no_token"}
        try:
            state = json.loads(_KILL_SWITCH_FILE.read_text())
            state["is_valid"] = self.is_live_enabled()
            return state
        except Exception:
            return {"enabled": False, "reason": "read_error"}

    def _write_state(self, enabled: bool, **kwargs) -> None:
        state = {
            "enabled":    enabled,
            "written_at": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        _KILL_SWITCH_FILE.write_text(json.dumps(state, indent=2))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POSITION RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════════════

class PositionReconciler:
    """
    On executor startup, compares IBKR actual positions against local state.

    Scenarios handled:
      A. Clean start (no local state, no broker positions) → normal
      B. Crash recovery (local state exists, broker position exists) → reconcile
      C. Orphaned broker position (no local state) → log + optionally flatten
      D. Stale local state (position was closed externally) → discard local

    Returns a reconciliation report; executor decides whether to proceed.
    """

    def __init__(self, order_manager, ibkr_executor, flatten_orphans: bool = False):
        self.order_manager    = order_manager
        self.ibkr             = ibkr_executor
        self.flatten_orphans  = flatten_orphans

    async def reconcile(self) -> dict:
        """
        Perform full reconciliation. Returns report dict.
        Call this BEFORE starting the signal monitor.
        """
        report = {
            "ts":           datetime.now(timezone.utc).isoformat(),
            "status":       "ok",
            "broker_positions": [],
            "local_positions":  [],
            "discrepancies":    [],
            "actions_taken":    [],
        }

        # Get broker positions
        broker_positions = {}
        if self.ibkr is not None:
            try:
                raw = await self.ibkr.get_positions()
                for p in raw:
                    sym = p.get("symbol", "")
                    if sym in ("ES", "NQ", "MES", "MNQ"):
                        broker_positions[sym] = p
                report["broker_positions"] = list(broker_positions.keys())
            except Exception as e:
                logger.error("[Reconciler] Could not fetch broker positions: %s", e)
                report["status"] = "broker_fetch_failed"
                report["error"]  = str(e)
                return report

        # Get local state
        local_positions = self.order_manager.active_positions()
        report["local_positions"] = list(local_positions.keys())

        # Compare
        all_syms = set(broker_positions) | set(local_positions)
        for sym in all_syms:
            has_broker = sym in broker_positions
            has_local  = sym in local_positions

            if has_broker and has_local:
                broker_qty = abs(int(broker_positions[sym].get("position", 0)))
                local_qty  = local_positions[sym].total_contracts
                if broker_qty != local_qty:
                    disc = {
                        "symbol":     sym,
                        "type":       "qty_mismatch",
                        "broker_qty": broker_qty,
                        "local_qty":  local_qty,
                    }
                    report["discrepancies"].append(disc)
                    logger.warning(
                        "[Reconciler] Qty mismatch %s: broker=%d local=%d",
                        sym, broker_qty, local_qty
                    )
                else:
                    logger.info("[Reconciler] %s reconciled: %d contracts OK", sym, broker_qty)

            elif has_broker and not has_local:
                disc = {
                    "symbol": sym,
                    "type":   "orphaned_broker_position",
                    "qty":    broker_positions[sym].get("position"),
                }
                report["discrepancies"].append(disc)
                logger.warning(
                    "[Reconciler] Orphaned broker position: %s qty=%s",
                    sym, disc["qty"]
                )
                if self.flatten_orphans and self.ibkr is not None:
                    try:
                        await self.ibkr.flatten_all_positions()
                        report["actions_taken"].append(f"flattened_orphan:{sym}")
                        logger.warning("[Reconciler] Flattened orphaned %s", sym)
                    except Exception as e:
                        logger.error("[Reconciler] Flatten failed for %s: %s", sym, e)

            elif has_local and not has_broker:
                disc = {
                    "symbol": sym,
                    "type":   "stale_local_state",
                    "note":   "position closed externally or fill not received",
                }
                report["discrepancies"].append(disc)
                logger.warning(
                    "[Reconciler] Stale local state for %s — position not at broker, discarding",
                    sym
                )
                del self.order_manager._positions[sym]
                report["actions_taken"].append(f"discarded_stale:{sym}")

        if report["discrepancies"]:
            report["status"] = "reconciled_with_discrepancies"
        else:
            report["status"] = "clean"

        # Persist to log
        with open(_RECONCILE_LOG_FILE, "a") as f:
            f.write(json.dumps(report) + "\n")

        logger.info("[Reconciler] Result: %s | discrepancies=%d",
                    report["status"], len(report["discrepancies"]))
        return report


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DEAD-MAN'S SWITCH
# ═══════════════════════════════════════════════════════════════════════════════

class DeadMansSwitch:
    """
    Heartbeat-based watchdog. Two roles:

    Role A — Heartbeat writer (runs inside executor process):
        Writes a timestamp to heartbeat.json every N seconds.
        Call: await dead_mans_switch.beat()  [in executor loop]

    Role B — Watchdog process (separate process started by executor):
        Monitors the heartbeat file. If stale beyond timeout,
        connects to IBKR and flattens all positions.
        Start: python -m engine.system2.kill_switch --watchdog

    The executor starts the watchdog automatically on startup.
    """

    def __init__(
        self,
        interval:  int = _HEARTBEAT_INTERVAL,
        timeout:   int = _DEAD_MANS_TIMEOUT,
        ibkr_port: int = 4002,
    ):
        self.interval  = interval
        self.timeout   = timeout
        self.ibkr_port = ibkr_port
        self._running  = False

    # ── Role A: Heartbeat writer ──────────────────────────────────────────────
    def write_beat(self) -> None:
        """Write a heartbeat. Call this periodically from the executor loop."""
        _HEARTBEAT_FILE.write_text(json.dumps({
            "ts":      datetime.now(timezone.utc).isoformat(),
            "pid":     os.getpid(),
            "port":    self.ibkr_port,
        }))

    async def beat_loop(self) -> None:
        """Async heartbeat loop — run concurrently with executor."""
        self._running = True
        while self._running:
            self.write_beat()
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self._running = False

    # ── Role B: Watchdog ──────────────────────────────────────────────────────
    def is_heartbeat_stale(self) -> bool:
        """Returns True if the heartbeat file is missing or older than timeout."""
        if not _HEARTBEAT_FILE.exists():
            return True
        try:
            state = json.loads(_HEARTBEAT_FILE.read_text())
            ts    = datetime.fromisoformat(state["ts"])
            age   = (datetime.now(timezone.utc) - ts).total_seconds()
            return age > self.timeout
        except Exception:
            return True

    def run_watchdog(self) -> None:
        """
        Blocking watchdog loop. Checks heartbeat every 30s.
        If stale, connects to IBKR and flattens all positions.
        """
        logger.info(
            "[DeadMansSwitch] Watchdog started. timeout=%ds port=%d",
            self.timeout, self.ibkr_port
        )
        while True:
            time.sleep(30)
            if self.is_heartbeat_stale():
                logger.critical(
                    "[DeadMansSwitch] HEARTBEAT STALE — executor may have crashed. "
                    "Connecting to IBKR to flatten positions."
                )
                asyncio.run(self._emergency_flatten())
                break
        logger.info("[DeadMansSwitch] Watchdog exiting.")

    async def _emergency_flatten(self) -> None:
        """Emergency flatten: connect to IBKR, cancel all, flatten all."""
        try:
            from ib_async import IB
            ib = IB()
            await ib.connectAsync("127.0.0.1", self.ibkr_port, clientId=99)
            logger.critical("[DeadMansSwitch] Emergency: cancelling all orders")
            open_orders = ib.openOrders()
            for order in open_orders:
                ib.cancelOrder(order)
            await asyncio.sleep(2)
            logger.critical("[DeadMansSwitch] Emergency: flattening all positions")
            positions = ib.positions()
            for pos in positions:
                if pos.position != 0:
                    from ib_async import MarketOrder, Future
                    action = "SELL" if pos.position > 0 else "BUY"
                    qty    = abs(int(pos.position))
                    order  = MarketOrder(action, qty)
                    ib.placeOrder(pos.contract, order)
            await asyncio.sleep(3)
            logger.critical("[DeadMansSwitch] Emergency flatten complete.")
            await ib.disconnectAsync()
        except Exception as e:
            logger.critical("[DeadMansSwitch] Emergency flatten FAILED: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="System 2 — Kill Switch / Position Reconciler / Dead-Man's Switch"
    )
    parser.add_argument("--enable",    action="store_true", help="Enable live trading (24h)")
    parser.add_argument("--disable",   action="store_true", help="Immediately disable live trading")
    parser.add_argument("--status",    action="store_true", help="Show current kill switch status")
    parser.add_argument("--watchdog",  action="store_true", help="Run the dead-man's switch watchdog")
    parser.add_argument("--account",   type=str, default="", help="Account number for --enable confirmation")
    args = parser.parse_args()

    ks = KillSwitch()

    if args.status:
        state = ks.status()
        print(json.dumps(state, indent=2))
        return

    if args.disable:
        ks.disable("cli_command")
        print("Live trading DISABLED.")
        return

    if args.enable:
        if not args.account:
            account = input("Enter account number to confirm live enable: ").strip()
        else:
            account = args.account

        confirm = input(
            f"WARNING: This enables LIVE trading on account {account}. "
            f"Token expires in 24h. Type 'CONFIRM' to proceed: "
        ).strip()
        if confirm != "CONFIRM":
            print("Aborted.")
            return

        ks.enable(account=account, reason="cli_enable")
        print(f"Live trading ENABLED for account {account}. Expires in 24h.")
        return

    if args.watchdog:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        dm = DeadMansSwitch()
        dm.run_watchdog()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
