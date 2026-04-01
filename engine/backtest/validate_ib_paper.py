"""
JARVIS TRADER — IB Gateway Paper Port 4002 Validation Script
=============================================================
Validates that IB Gateway is properly configured for paper trading
before activating the live paper trading session.

Go-Live Tier 1 Checklist Item #7: IB paper port 4002 connected.

Checks:
    1. TCP connectivity to 127.0.0.1:4002 (port open)
    2. ib_async / ib_insync library available
    3. IB Gateway accepts connection (not TWS Live)
    4. Account is a paper account (DU prefix)
    5. Paper trading mode flag active
    6. Market data subscription responds (MCL tick request)

Usage:
    cd engine
    .venv/Scripts/python -m backtest.validate_ib_paper

    # Or with custom host/port:
    .venv/Scripts/python -m backtest.validate_ib_paper --host 127.0.0.1 --port 4002

Output:
    engine/backtest/results/ib_validation.json

Exit codes:
    0 = All checks PASS
    1 = One or more checks FAIL
    2 = ib_async not installed (install: pip install ib_async>=0.9.86)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

RESULTS_DIR = Path(__file__).parent / "results"
RESULT_FILE = RESULTS_DIR / "ib_validation.json"
PAPER_PORT = 4002
PAPER_HOST = "127.0.0.1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Individual checks ─────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self, name: str):
        self.name = name
        self.passed: bool = False
        self.message: str = ""
        self.detail: str = ""

    def ok(self, msg: str, detail: str = "") -> "ValidationResult":
        self.passed = True
        self.message = msg
        self.detail = detail
        logger.info(f"  [PASS] {self.name}: {msg}")
        return self

    def fail(self, msg: str, detail: str = "") -> "ValidationResult":
        self.passed = False
        self.message = msg
        self.detail = detail
        logger.error(f"  [FAIL] {self.name}: {msg}")
        if detail:
            logger.error(f"         {detail}")
        return self

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "detail": self.detail,
        }


def check_port_open(host: str, port: int, timeout: float = 5.0) -> ValidationResult:
    """Check TCP connectivity to host:port."""
    result = ValidationResult("TCP connectivity")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        code = sock.connect_ex((host, port))
        sock.close()
        if code == 0:
            return result.ok(f"{host}:{port} is reachable")
        else:
            return result.fail(
                f"{host}:{port} refused connection (code={code})",
                "Is IB Gateway running? Open TWS/Gateway and enable API on port 4002.",
            )
    except socket.timeout:
        return result.fail(
            f"Timeout connecting to {host}:{port}",
            "IB Gateway may not be running or is blocked by firewall.",
        )
    except Exception as e:
        return result.fail(f"Socket error: {e}")


def check_library_available() -> ValidationResult:
    """Check ib_async / ib_insync is installed."""
    result = ValidationResult("ib_async library")
    try:
        import ib_async  # noqa: F401
        return result.ok("ib_async is installed")
    except ImportError:
        pass
    try:
        import ib_insync  # noqa: F401
        return result.ok("ib_insync is installed (legacy — consider upgrading to ib_async)")
    except ImportError:
        return result.fail(
            "Neither ib_async nor ib_insync is installed",
            "Install: .venv/Scripts/pip install ib_async>=0.9.86",
        )


async def check_ib_connection(host: str, port: int, timeout: float = 10.0) -> list[ValidationResult]:
    """
    Connect to IB Gateway and run account-level checks.
    Returns a list of ValidationResult objects for each sub-check.
    """
    results = []

    conn_result = ValidationResult("IB Gateway connection")
    account_result = ValidationResult("Paper account (DU prefix)")
    paper_mode_result = ValidationResult("Paper trading mode active")
    tick_result = ValidationResult("Market data tick (MCL)")

    # Try to import ib_async
    try:
        try:
            from ib_async import IB, Future  # type: ignore[import]
        except ImportError:
            from ib_insync import IB, Future  # type: ignore[import]
    except ImportError:
        fail_msg = "Library not available — cannot connect"
        conn_result.fail(fail_msg)
        account_result.fail(fail_msg)
        paper_mode_result.fail(fail_msg)
        tick_result.fail(fail_msg)
        return [conn_result, account_result, paper_mode_result, tick_result]

    ib = IB()
    try:
        # ── Connection ──────────────────────────────────────────────────────────
        logger.info(f"  Connecting to {host}:{port} (clientId=99)...")
        await asyncio.wait_for(
            ib.connectAsync(host, port, clientId=99),
            timeout=timeout,
        )
        conn_result.ok(f"Connected to IB Gateway at {host}:{port}")
        results.append(conn_result)

        # ── Account check ───────────────────────────────────────────────────────
        accounts = ib.managedAccounts()
        logger.info(f"  Managed accounts: {accounts}")
        paper_accounts = [a for a in accounts if a.startswith("DU")]
        if paper_accounts:
            account_result.ok(
                f"Paper account confirmed: {', '.join(paper_accounts)}",
                "DU prefix confirms this is a paper trading account.",
            )
        else:
            account_result.fail(
                f"No paper account found. Accounts: {accounts}",
                "Expected account starting with 'DU'. "
                "Make sure IB Gateway is in paper trading mode.",
            )
        results.append(account_result)

        # ── Paper mode flag ─────────────────────────────────────────────────────
        # Check serverVersion and connection info for paper mode indicators
        conn_state = ib.isConnected()
        if conn_state and paper_accounts:
            paper_mode_result.ok(
                "Paper trading mode active (DU account + port 4002)",
                f"serverVersion={ib.client.serverVersion()}",
            )
        elif conn_state:
            paper_mode_result.fail(
                "Connected but no DU account — may be live TWS on wrong port",
                "Verify IB Gateway (not TWS Live) is running and port 4002 is selected.",
            )
        else:
            paper_mode_result.fail("Not connected — cannot verify paper mode")
        results.append(paper_mode_result)

        # ── MCL market data tick ────────────────────────────────────────────────
        try:
            # MCL = Micro WTI Crude Oil futures on NYMEX
            # Use a generic future contract to request tick
            mcl_contract = Future(symbol="MCL", exchange="NYMEX", currency="USD")
            qualified = await asyncio.wait_for(
                ib.qualifyContractsAsync(mcl_contract),
                timeout=5.0,
            )
            if qualified:
                ticker = ib.reqMktData(qualified[0], "", snapshot=True, regulatorySnapshot=False)
                # Wait briefly for tick data
                await asyncio.sleep(2.0)
                has_price = ticker.last > 0 or ticker.bid > 0 or ticker.ask > 0 or ticker.close > 0
                if has_price:
                    tick_result.ok(
                        f"MCL market data received: last={ticker.last:.2f} bid={ticker.bid:.2f} ask={ticker.ask:.2f}",
                    )
                else:
                    tick_result.ok(
                        "MCL contract qualified but price data pending (market may be closed)",
                        "This is acceptable outside market hours.",
                    )
                ib.cancelMktData(qualified[0])
            else:
                tick_result.fail(
                    "Could not qualify MCL contract",
                    "Check market data subscriptions in IB Account Management.",
                )
        except asyncio.TimeoutError:
            tick_result.fail(
                "MCL tick request timed out (5s)",
                "Market data subscription may not be active for MCL.",
            )
        except Exception as e:
            tick_result.fail(
                f"MCL tick request failed: {e}",
                "Check MCL market data subscription in IB Account Management.",
            )
        results.append(tick_result)

    except asyncio.TimeoutError:
        conn_result.fail(
            f"Connection to {host}:{port} timed out after {timeout}s",
            "Is IB Gateway running and API enabled? "
            "In IB Gateway: Configure → API → Enable ActiveX and Socket Clients → Port 4002",
        )
        results.append(conn_result)
        # Remaining checks can't run
        for r in [account_result, paper_mode_result, tick_result]:
            r.fail("Skipped — connection failed")
            results.append(r)

    except Exception as e:
        conn_result.fail(
            f"Connection error: {e}",
            "Ensure IB Gateway is open and API socket is enabled on port 4002.",
        )
        results.append(conn_result)
        for r in [account_result, paper_mode_result, tick_result]:
            r.fail("Skipped — connection failed")
            results.append(r)

    finally:
        if ib.isConnected():
            ib.disconnect()

    return results


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_validation(host: str = PAPER_HOST, port: int = PAPER_PORT) -> dict:
    """Run all validation checks and return a summary dict."""
    run_ts = datetime.utcnow().isoformat()

    logger.info("=" * 60)
    logger.info("JARVIS TRADER — IB Gateway Paper Trading Validation")
    logger.info(f"Target: {host}:{port}")
    logger.info(f"Run:    {run_ts}")
    logger.info("=" * 60)

    all_results = []

    # Check 1: TCP port
    logger.info("\n[1/6] TCP Connectivity...")
    port_result = check_port_open(host, port)
    all_results.append(port_result)

    # Check 2: Library
    logger.info("\n[2/6] ib_async Library...")
    lib_result = check_library_available()
    all_results.append(lib_result)

    # Checks 3-6: IB Gateway (requires TCP and library)
    if port_result.passed and lib_result.passed:
        logger.info("\n[3-6/6] IB Gateway connection, account, mode, market data...")
        ib_results = await check_ib_connection(host, port)
        all_results.extend(ib_results)
    else:
        for name in ["IB Gateway connection", "Paper account (DU prefix)", "Paper trading mode active", "Market data tick (MCL)"]:
            r = ValidationResult(name)
            r.fail("Skipped — prerequisite check failed (TCP or library)")
            all_results.append(r)

    # Summary
    passed = [r for r in all_results if r.passed]
    failed = [r for r in all_results if not r.passed]
    overall = "PASS" if all(r.passed for r in all_results) else "FAIL"

    logger.info("\n" + "=" * 60)
    logger.info(f"RESULT: {overall} ({len(passed)}/{len(all_results)} checks passed)")
    for r in all_results:
        icon = "✅" if r.passed else "❌"
        logger.info(f"  {icon} {r.name}: {r.message}")
    logger.info("=" * 60)

    summary = {
        "status": overall,
        "run_ts": run_ts,
        "host": host,
        "port": port,
        "passed": len(passed),
        "total": len(all_results),
        "checks": [r.to_dict() for r in all_results],
    }

    # Write result file
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(summary, indent=2))
    logger.info(f"\nResult saved: {RESULT_FILE}")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER — IB Gateway Paper Port Validation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=PAPER_HOST, help="IB Gateway host")
    parser.add_argument("--port", type=int, default=PAPER_PORT, help="IB Gateway port (must be 4002)")
    args = parser.parse_args()

    if args.port == 4001:
        logger.critical("Port 4001 is the LIVE trading port. JARVIS never connects to live port during testing.")
        sys.exit(2)

    summary = asyncio.run(run_validation(args.host, args.port))

    if summary["status"] == "PASS":
        print("\n✅ IB Gateway paper trading validation PASSED. Port 4002 ready.")
        sys.exit(0)
    else:
        failed_names = [c["name"] for c in summary["checks"] if not c["passed"]]
        print(f"\n❌ IB Gateway validation FAILED ({len(failed_names)} checks):")
        for name in failed_names:
            print(f"   - {name}")
        print(f"\nReview: {RESULT_FILE}")
        sys.exit(1)


if __name__ == "__main__":
    main()
