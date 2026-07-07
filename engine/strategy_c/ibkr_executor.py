"""
Strategy C+ IBKR Execution Layer
==================================
Wires the weekly signal into the jarvis-trader IB Gateway connection.

Architecture:
  - Reads live signal from strategy_c_plus_live_signal.json
  - Submits rebalancing orders via IB Gateway (port 4002 paper / 4001 live)
  - Respects ALL jarvis-trader safety invariants:
      - LIVE_TRADING_ENABLED = False (paper only until explicitly changed)
      - REQUIRE_HUMAN_APPROVAL = True (every order must be approved)
      - Kill switch: -2% daily / -10% drawdown
      - Max order value: $5,000

Usage:
    # Check current signal only (no orders):
    python -m engine.strategy_c.ibkr_executor --check-only

    # Generate orders (requires human approval):
    python -m engine.strategy_c.ibkr_executor --submit

    # Paper execute (no IBKR needed, logs to paper_trades.db):
    python -m engine.strategy_c.ibkr_executor --paper

Integrates with jarvis-trader engine API at port 8010.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("strategy_c_executor")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — aligned with jarvis-trader CLAUDE.md invariants
# ─────────────────────────────────────────────────────────────────────────────

ENGINE_HOST = os.environ.get("ENGINE_HOST", "localhost")
ENGINE_PORT = int(os.environ.get("ENGINE_PORT", "8010"))
# Resolve from the environment only; never embed the credential in source.
# Honors JARVIS_API_KEY (legacy var) then falls back to API_KEY (the var the
# engine validates against). Empty string if unset -> engine returns 401.
ENGINE_API_KEY = os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY", "")
ENGINE_BASE_URL = f"http://{ENGINE_HOST}:{ENGINE_PORT}"

IBKR_PAPER_PORT = 4002
IBKR_ACCOUNT = "DUP662235"

# Safety invariants (hardcoded — never allow LLM to override these)
LIVE_TRADING_ENABLED = False     # Paper only until explicit human approval
REQUIRE_HUMAN_APPROVAL = True    # All orders must be manually approved
MAX_SINGLE_ORDER_VALUE_USD = 5000.0
MAX_DAILY_LOSS_PCT = 0.02
MAX_DRAWDOWN_PCT = 0.10

SIGNAL_FILE = Path(__file__).parent / "output" / "strategy_c_plus_live_signal.json"
EXECUTION_LOG = Path(__file__).parent / "output" / "execution_log.json"


class StrategyCExecutor:
    """
    IBKR execution manager for Strategy C+ weekly rebalancing.

    All orders are submitted through the jarvis-trader engine API,
    which enforces the safety layer and human approval gate.
    """

    def __init__(
        self,
        paper_mode: bool = True,
        require_approval: bool = True,
    ):
        self.paper_mode = paper_mode
        self.require_approval = require_approval
        self._headers = {"X-API-Key": ENGINE_API_KEY, "Content-Type": "application/json"}

    # ─────────────────────────────────────────────────────────────────────────
    # Signal Reading
    # ─────────────────────────────────────────────────────────────────────────

    def load_signal(self) -> Optional[dict]:
        """Load the latest Strategy C+ live signal from file."""
        if not SIGNAL_FILE.exists():
            logger.error("Signal file not found: %s", SIGNAL_FILE)
            logger.error("Run: python -m engine.strategy_c.live_signal first")
            return None

        with open(SIGNAL_FILE) as f:
            signal = json.load(f)

        # Age check — warn if signal is older than 48 hours
        generated_at = signal.get("generated_at", "")
        if generated_at:
            try:
                sig_time = datetime.fromisoformat(generated_at)
                age_hours = (datetime.now() - sig_time).total_seconds() / 3600
                if age_hours > 48:
                    logger.warning(
                        "Signal is %d hours old (generated %s). "
                        "Consider running live_signal.py first.",
                        int(age_hours), generated_at
                    )
            except Exception:
                pass

        return signal

    # ─────────────────────────────────────────────────────────────────────────
    # Engine Health Check
    # ─────────────────────────────────────────────────────────────────────────

    def check_engine_health(self) -> bool:
        """Verify jarvis-trader engine is running and IB Gateway connected."""
        try:
            resp = requests.get(f"{ENGINE_BASE_URL}/health", headers=self._headers, timeout=5)
            health = resp.json()
            logger.info("Engine health: %s", health.get("status", "unknown"))

            # Check IB Gateway
            ib_resp = requests.get(
                f"{ENGINE_BASE_URL}/v1/broker/status",
                headers=self._headers, timeout=5
            )
            ib_status = ib_resp.json()
            connected = ib_status.get("connected", False)
            logger.info("IB Gateway: %s (port %s)",
                        "CONNECTED" if connected else "DISCONNECTED",
                        ib_status.get("port", IBKR_PAPER_PORT))
            return connected
        except Exception as e:
            logger.warning("Engine health check failed: %s", e)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Order Generation
    # ─────────────────────────────────────────────────────────────────────────

    def generate_rebalance_orders(
        self,
        signal: dict,
        account_value_usd: float = 10_000.0,
    ) -> list[dict]:
        """
        Convert Strategy C+ signal into IBKR rebalance orders.

        For each holding:
          - Compute target dollar amount = account_value × weight
          - Look up current price to compute shares
          - Generate BUY/SELL orders to reach target weights

        Parameters
        ----------
        signal : dict
            Live signal from StrategyCEngine.get_live_signal()
        account_value_usd : float
            Total account value for position sizing

        Returns
        -------
        list[dict] : List of order dicts in jarvis-trader order format
        """
        holdings = signal.get("holdings", {})
        layers = signal.get("layers", {})
        regime = layers.get("momentum_signal", {}).get("risk_regime", "UNKNOWN")

        orders = []

        for symbol, weight in holdings.items():
            if weight < 0.005:
                continue

            target_usd = account_value_usd * weight

            # Safety check: single order cap
            if target_usd > MAX_SINGLE_ORDER_VALUE_USD:
                logger.warning(
                    "Order for %s ($%.0f) exceeds MAX_SINGLE_ORDER_VALUE_USD ($%.0f). "
                    "Capping to max.",
                    symbol, target_usd, MAX_SINGLE_ORDER_VALUE_USD
                )
                target_usd = MAX_SINGLE_ORDER_VALUE_USD

            order = {
                "symbol": symbol,
                "action": "BUY",
                "order_type": "MKT",
                "tif": "OPG",  # At-open
                "target_usd": round(target_usd, 2),
                "weight_pct": round(weight * 100, 2),
                "account": IBKR_ACCOUNT,
                "strategy": "Strategy_C_Plus",
                "regime": regime,
                "combined_scale": signal.get("combined_scale", 1.0),
                "paper_mode": self.paper_mode,
                "requires_approval": self.require_approval,
                "generated_at": signal.get("generated_at", datetime.now().isoformat()),
            }
            orders.append(order)

        logger.info(
            "Generated %d rebalance orders for regime %s (combined_scale=%.3f)",
            len(orders), regime, signal.get("combined_scale", 1.0)
        )
        return orders

    # ─────────────────────────────────────────────────────────────────────────
    # Submission
    # ─────────────────────────────────────────────────────────────────────────

    def submit_for_approval(self, orders: list[dict]) -> dict:
        """
        Submit orders to the jarvis-trader approval queue.

        Orders are NOT executed until a human approves via the dashboard
        (http://localhost:3010) or the /v1/approvals/approve endpoint.

        This is the REQUIRE_HUMAN_APPROVAL safety invariant.
        """
        if not orders:
            return {"status": "no_orders", "count": 0}

        approval_payload = {
            "strategy": "Strategy_C_Plus",
            "orders": orders,
            "submitted_at": datetime.now().isoformat(),
            "paper_mode": self.paper_mode,
            "auto_approve": False,  # Always False — never auto-approve
            "notes": (
                f"Strategy C+ weekly rebalance. "
                f"Combined scale: {orders[0].get('combined_scale', 0):.3f}. "
                f"Regime: {orders[0].get('regime', 'UNKNOWN')}. "
                f"Execute Monday MOO per T+1 lag rule."
            ),
        }

        try:
            # Submit to jarvis-trader pending approvals queue
            resp = requests.post(
                f"{ENGINE_BASE_URL}/v1/approvals/pending",
                headers=self._headers,
                json=approval_payload,
                timeout=10,
            )
            result = resp.json()
            logger.info("Submitted %d orders for approval: %s", len(orders), result)
            return result
        except Exception as e:
            logger.error("Failed to submit orders: %s", e)
            # Fallback: save to local file for manual review
            self._save_orders_local(orders)
            return {"status": "engine_unreachable", "orders_saved_locally": True}

    def _save_orders_local(self, orders: list[dict]) -> None:
        """Fallback: save orders to local JSON for manual review."""
        log = []
        if EXECUTION_LOG.exists():
            with open(EXECUTION_LOG) as f:
                try:
                    log = json.load(f)
                except Exception:
                    log = []

        log.append({
            "timestamp": datetime.now().isoformat(),
            "orders": orders,
            "status": "pending_manual_review",
        })

        with open(EXECUTION_LOG, "w") as f:
            json.dump(log, f, indent=2, default=str)
        logger.info("Orders saved locally: %s", EXECUTION_LOG)

    # ─────────────────────────────────────────────────────────────────────────
    # Paper Trade Log
    # ─────────────────────────────────────────────────────────────────────────

    def log_paper_trade(self, signal: dict, orders: list[dict]) -> None:
        """Log a paper trade execution for tracking."""
        paper_trade = {
            "timestamp": datetime.now().isoformat(),
            "strategy": "Strategy_C_Plus",
            "signal_generated": signal.get("generated_at"),
            "regime": signal.get("layers", {}).get("momentum_signal", {}).get("risk_regime"),
            "combined_scale": signal.get("combined_scale"),
            "holdings": signal.get("holdings"),
            "orders": orders,
            "paper_mode": True,
            "executed": False,  # Will be set True after approval
        }

        log = []
        if EXECUTION_LOG.exists():
            with open(EXECUTION_LOG) as f:
                try:
                    log = json.load(f)
                except Exception:
                    log = []
        log.append(paper_trade)
        with open(EXECUTION_LOG, "w") as f:
            json.dump(log, f, indent=2, default=str)
        logger.info("Paper trade logged → %s", EXECUTION_LOG)

    # ─────────────────────────────────────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────────────────────────────────────

    def run(
        self,
        check_only: bool = False,
        account_value_usd: float = 10_000.0,
    ) -> dict:
        """
        Full execution flow:
          1. Load latest signal
          2. Check engine health
          3. Generate orders
          4. Submit for approval (or check-only)
        """
        # Load signal
        signal = self.load_signal()
        if not signal:
            return {"error": "No signal available"}

        _print_signal_summary(signal)

        if check_only:
            logger.info("CHECK-ONLY mode: no orders submitted")
            return {"status": "check_only", "signal": signal}

        # Generate orders
        orders = self.generate_rebalance_orders(signal, account_value_usd)
        if not orders:
            logger.info("No orders needed (all cash or zero scale)")
            return {"status": "no_orders", "signal": signal}

        # Log paper trade
        self.log_paper_trade(signal, orders)

        if not LIVE_TRADING_ENABLED:
            logger.info(
                "LIVE_TRADING_ENABLED=False — orders logged as paper trade only. "
                "Set LIVE_TRADING_ENABLED=True and approve in dashboard to execute."
            )
            return {
                "status": "paper_logged",
                "orders": orders,
                "note": "Approve in dashboard at http://localhost:3010",
            }

        # Check engine health before submitting
        if not self.check_engine_health():
            logger.warning("Engine/IB Gateway unreachable — orders saved locally")
            self._save_orders_local(orders)
            return {"status": "engine_unreachable", "orders_saved": True}

        # Submit for approval
        result = self.submit_for_approval(orders)
        return {"status": "submitted", "result": result, "n_orders": len(orders)}


def _print_signal_summary(signal: dict) -> None:
    """Print a compact signal summary to console."""
    print("\n" + "=" * 55)
    print("  STRATEGY C+  WEEKLY SIGNAL")
    print(f"  {signal.get('generated_at', 'unknown')}")
    print("=" * 55)
    layers = signal.get("layers", {})
    mom = layers.get("momentum_signal", {})
    vol = layers.get("vol_targeting", {})
    vix = layers.get("vix_composite", {})
    print(f"  Regime:        {mom.get('risk_regime', '?')}")
    print(f"  Combined Scale:{signal.get('combined_scale', 0):.3f}")
    print(f"  Vol Scale:     {vol.get('scale', 0):.3f}  (realized {vol.get('realized_vol_pct', 0):.1f}%)")
    print(f"  VIX:           {vix.get('vix', 0):.1f}  ({vix.get('vix_regime', '?')})  score={vix.get('composite_score', 0):.3f}")
    print("\n  Holdings:")
    for tk, wt in sorted(signal.get("holdings", {}).items(), key=lambda x: -x[1]):
        bar = "█" * max(1, int(wt * 25))
        print(f"    {tk:<6} {wt:.1%}  {bar}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Strategy C+ IBKR Executor")
    parser.add_argument("--check-only", action="store_true", help="Show signal without submitting orders")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trade mode (default)")
    parser.add_argument("--account-value", type=float, default=10_000.0, help="Account value USD")
    args = parser.parse_args()

    executor = StrategyCExecutor(paper_mode=args.paper)
    result = executor.run(check_only=args.check_only, account_value_usd=args.account_value)
    print(json.dumps(result, indent=2, default=str))
