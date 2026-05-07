"""
Strategy C+ Paper Dry-Run
==========================
Standalone script — does NOT require ibapi or ib_insync.

Reads the live signal JSON, formats orders exactly as ibkr_executor.py would,
auto-approves in dry-run mode, writes a paper_trade_log entry to
execution_log.json, and prints a clean execution summary.

Usage:
    python paper_dryrun.py
    python paper_dryrun.py --account-value 25000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
SIGNAL_FILE = HERE / "output" / "strategy_c_plus_live_signal.json"
EXECUTION_LOG = HERE / "output" / "execution_log.json"

# ── Safety constants (mirror ibkr_executor.py) ─────────────────────────────────
IBKR_ACCOUNT = "DUP662235"
LIVE_TRADING_ENABLED = False
REQUIRE_HUMAN_APPROVAL = True
MAX_SINGLE_ORDER_VALUE_USD = 5000.0


def load_signal() -> dict:
    if not SIGNAL_FILE.exists():
        sys.exit(f"[ERROR] Signal file not found: {SIGNAL_FILE}\n"
                 "  Run: python -m engine.strategy_c.live_signal first")
    with open(SIGNAL_FILE) as f:
        signal = json.load(f)
    # Age warning
    generated_at = signal.get("generated_at", "")
    if generated_at:
        try:
            age_hours = (datetime.now() - datetime.fromisoformat(generated_at)).total_seconds() / 3600
            if age_hours > 48:
                print(f"[WARN] Signal is {int(age_hours)}h old (generated {generated_at}). "
                      "Consider refreshing via live_signal.py first.")
        except Exception:
            pass
    return signal


def generate_orders(signal: dict, account_value_usd: float) -> list[dict]:
    holdings = signal.get("holdings", {})
    regime = signal.get("layers", {}).get("momentum_signal", {}).get("risk_regime", "UNKNOWN")
    orders = []
    for symbol, weight in holdings.items():
        if weight < 0.005:
            continue
        target_usd = account_value_usd * weight
        capped = False
        if target_usd > MAX_SINGLE_ORDER_VALUE_USD:
            print(f"[WARN] {symbol} target ${target_usd:,.0f} exceeds max ${MAX_SINGLE_ORDER_VALUE_USD:,.0f} — capping.")
            target_usd = MAX_SINGLE_ORDER_VALUE_USD
            capped = True
        orders.append({
            "symbol": symbol,
            "action": "BUY",
            "order_type": "MKT",
            "tif": "OPG",
            "target_usd": round(target_usd, 2),
            "weight_pct": round(weight * 100, 2),
            "account": IBKR_ACCOUNT,
            "strategy": "Strategy_C_Plus",
            "regime": regime,
            "combined_scale": signal.get("combined_scale", 1.0),
            "paper_mode": True,
            "requires_approval": REQUIRE_HUMAN_APPROVAL,
            "generated_at": signal.get("generated_at", datetime.now().isoformat()),
            "capped_to_max": capped,
        })
    return orders


def print_summary(signal: dict, orders: list[dict]) -> None:
    print("\n" + "=" * 58)
    print("  STRATEGY C+  PAPER DRY-RUN")
    print(f"  Signal:  {signal.get('generated_at', 'unknown')}")
    print(f"  Run at:  {datetime.now().isoformat()}")
    print("=" * 58)
    layers = signal.get("layers", {})
    mom = layers.get("momentum_signal", {})
    vol = layers.get("vol_targeting", {})
    vix = layers.get("vix_composite", {})
    print(f"  Regime:         {mom.get('risk_regime', '?')}")
    print(f"  Combined Scale: {signal.get('combined_scale', 0):.4f}")
    print(f"  Vol Scale:      {vol.get('scale', 0):.4f}  (realized {vol.get('realized_vol_pct', 0):.1f}%)")
    print(f"  VIX:            {vix.get('vix', 0):.1f}  ({vix.get('vix_regime', '?')})  "
          f"score={vix.get('composite_score', 0):.4f}")
    print(f"\n  Orders ({len(orders)}):")
    print(f"  {'Symbol':<8} {'Action':<6} {'Weight':>8}  {'Target $':>10}  {'Type':<4}  {'TIF':<5}")
    print(f"  {'-'*8} {'-'*6} {'-'*8}  {'-'*10}  {'-'*4}  {'-'*5}")
    for o in orders:
        print(f"  {o['symbol']:<8} {o['action']:<6} {o['weight_pct']:>7.2f}%  ${o['target_usd']:>9,.2f}  "
              f"{o['order_type']:<4}  {o['tif']:<5}")
    print(f"\n  Account:  {IBKR_ACCOUNT}  (PAPER)")
    print("  Execute:  Monday MOO (Market On Open)")
    print(f"  Safety:   LIVE_TRADING_ENABLED={LIVE_TRADING_ENABLED}  |  "
          f"REQUIRE_HUMAN_APPROVAL={REQUIRE_HUMAN_APPROVAL}")
    print("=" * 58 + "\n")


def write_log(signal: dict, orders: list[dict]) -> None:
    log = []
    if EXECUTION_LOG.exists():
        with open(EXECUTION_LOG) as f:
            try:
                log = json.load(f)
            except Exception:
                log = []

    entry = {
        "timestamp": datetime.now().isoformat(),
        "run_type": "paper_dryrun_standalone",
        "strategy": "Strategy_C_Plus",
        "signal_generated": signal.get("generated_at"),
        "regime": signal.get("layers", {}).get("momentum_signal", {}).get("risk_regime"),
        "combined_scale": signal.get("combined_scale"),
        "holdings": signal.get("holdings"),
        "orders": orders,
        "paper_mode": True,
        "executed": False,
        "auto_approved_dryrun": True,
        "note": "Standalone dry-run — no IBKR connection required",
    }
    log.append(entry)
    EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXECUTION_LOG, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"[OK] Paper trade logged → {EXECUTION_LOG}")


def main():
    parser = argparse.ArgumentParser(description="Strategy C+ Paper Dry-Run (no IBKR required)")
    parser.add_argument("--account-value", type=float, default=10_000.0,
                        help="Total account value in USD (default: 10000)")
    parser.add_argument("--no-log", action="store_true", help="Skip writing to execution_log.json")
    args = parser.parse_args()

    signal = load_signal()
    orders = generate_orders(signal, args.account_value)
    print_summary(signal, orders)

    if not args.no_log:
        write_log(signal, orders)

    print(json.dumps({
        "status": "paper_dryrun_ok",
        "orders_count": len(orders),
        "total_target_usd": sum(o["target_usd"] for o in orders),
        "regime": signal.get("layers", {}).get("momentum_signal", {}).get("risk_regime"),
        "combined_scale": signal.get("combined_scale"),
    }, indent=2))


if __name__ == "__main__":
    main()
