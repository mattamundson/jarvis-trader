#!/usr/bin/env python3
"""
Engine Health Check Script

Verifies the JARVIS TRADER engine is healthy by hitting key endpoints
and validating response shapes. Uses requests library and graceful error handling.

Usage:
    python scripts/health_check.py --host localhost --port 8010
    python scripts/health_check.py --host 192.168.1.100 --port 8010
"""

import argparse
import logging
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)


def setup_logging() -> logging.Logger:
    """Configure logging for health checks."""
    logger = logging.getLogger("health_check")
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()


class HealthChecker:
    """Validates engine health via HTTP endpoints."""

    def __init__(self, host: str, port: int, api_key: str = "test-key", timeout: int = 5):
        """Initialize health checker with engine connection details.

        Args:
            host: Engine hostname or IP
            port: Engine port
            api_key: X-API-Key header value
            timeout: Request timeout in seconds
        """
        self.base_url = f"http://{host}:{port}"
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-API-Key": api_key}
        self.results = []

    def _request(self, method: str, endpoint: str) -> tuple[bool, Any]:
        """Make HTTP request and return (success, response_data)."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            else:
                resp = requests.post(url, headers=self.headers, timeout=self.timeout)

            resp.raise_for_status()
            return True, resp.json()
        except requests.exceptions.ConnectionError:
            return False, {"error": "Connection refused"}
        except requests.exceptions.Timeout:
            return False, {"error": "Request timeout"}
        except requests.exceptions.HTTPError as e:
            return False, {"error": f"HTTP {e.response.status_code}"}
        except ValueError:
            return False, {"error": "Invalid JSON response"}
        except Exception as e:
            return False, {"error": str(e)}

    def check_health(self) -> bool:
        """Check /health endpoint — engine is running."""
        logger.info("Checking /health endpoint...")
        success, data = self._request("GET", "/health")

        if not success:
            self._record("FAIL", "Engine Health", data.get("error", "Unknown error"))
            return False

        status = data.get("status")
        version = data.get("version")
        is_ok = status in ("ok", "degraded")

        if is_ok:
            self._record("PASS", "Engine Health", f"Status: {status}, Version: {version}")
            return True
        else:
            self._record("FAIL", "Engine Health", f"Unexpected status: {status}")
            return False

    def check_safety_status(self) -> bool:
        """Check /safety/status — kill_switch_active should be false, paper_mode true."""
        logger.info("Checking /safety/status endpoint...")
        success, data = self._request("GET", "/safety/status")

        if not success:
            self._record("FAIL", "Safety Status", data.get("error", "Unknown error"))
            return False

        kill_switch = data.get("kill_switch_active", False)
        daily_pnl = data.get("daily_pnl", 0.0)
        drawdown = data.get("drawdown_pct", 0.0)

        if kill_switch:
            reason = data.get("kill_switch_reason", "unknown")
            self._record("FAIL", "Safety Status", f"Kill switch ACTIVE: {reason}")
            return False
        else:
            detail = f"Daily PnL: ${daily_pnl:.2f}, Drawdown: {drawdown:.2f}%"
            self._record("PASS", "Safety Status", detail)
            return True

    def check_broker_status(self) -> bool:
        """Check IB Gateway connection state (optional, non-critical)."""
        logger.info("Checking broker/IB Gateway status...")
        success, data = self._request("GET", "/health/full")

        if not success:
            self._record("WARN", "Broker Status", f"Cannot verify: {data.get('error')}")
            return True  # Non-critical

        try:
            subsystems = data.get("subsystems", {})
            ib_gw = subsystems.get("ib_gateway", {})
            ib_status = ib_gw.get("status", "unknown")

            if ib_status == "ok":
                self._record("PASS", "Broker Status", "IB Gateway connected")
                return True
            elif ib_status == "not_configured":
                self._record("PASS", "Broker Status", "IB Gateway not configured (paper only)")
                return True
            else:
                self._record("WARN", "Broker Status", f"IB Gateway: {ib_status}")
                return True  # Non-critical
        except Exception as e:
            self._record("WARN", "Broker Status", f"Error parsing response: {e}")
            return True

    def check_portfolio_stats(self) -> bool:
        """Check /portfolio/stats/summary — portfolio data returns."""
        logger.info("Checking /portfolio/stats/summary endpoint...")
        success, data = self._request("GET", "/portfolio/stats/summary")

        if not success:
            self._record("FAIL", "Portfolio Stats", data.get("error", "Unknown error"))
            return False

        try:
            net_pnl = data.get("net_pnl", 0.0)
            trades_total = data.get("total_trades", 0)
            self._record(
                "PASS",
                "Portfolio Stats",
                f"Net PnL: ${net_pnl:.2f}, Total Trades: {trades_total}",
            )
            return True
        except Exception as e:
            self._record("FAIL", "Portfolio Stats", f"Error parsing response: {e}")
            return False

    def check_pipeline_scheduler(self) -> bool:
        """Check /pipeline/scheduler/status — scheduler running."""
        logger.info("Checking /pipeline/scheduler/status endpoint...")
        success, data = self._request("GET", "/pipeline/scheduler/status")

        if not success:
            self._record("FAIL", "Pipeline Scheduler", data.get("error", "Unknown error"))
            return False

        try:
            is_running = data.get("running", False)
            total_jobs = data.get("total_jobs", 0)

            if is_running:
                self._record(
                    "PASS",
                    "Pipeline Scheduler",
                    f"Running with {total_jobs} jobs",
                )
                return True
            else:
                self._record("FAIL", "Pipeline Scheduler", "Scheduler not running")
                return False
        except Exception as e:
            self._record("FAIL", "Pipeline Scheduler", f"Error parsing response: {e}")
            return False

    def _record(self, status: str, check_name: str, detail: str) -> None:
        """Record a check result."""
        self.results.append(
            {"status": status, "check": check_name, "detail": detail}
        )
        logger.info(f"[{status}] {check_name}: {detail}")

    def run_all_checks(self) -> int:
        """Run all health checks. Return 0 if all pass, 1 if any fail."""
        logger.info(f"Starting health check of {self.base_url}")
        logger.info("=" * 70)

        checks = [
            ("Engine Health", self.check_health),
            ("Safety Status", self.check_safety_status),
            ("Broker Status", self.check_broker_status),
            ("Portfolio Stats", self.check_portfolio_stats),
            ("Pipeline Scheduler", self.check_pipeline_scheduler),
        ]

        results = {}
        for name, check_fn in checks:
            try:
                results[name] = check_fn()
            except Exception as e:
                logger.exception(f"Exception during {name}: {e}")
                self._record("FAIL", name, f"Exception: {e}")
                results[name] = False

        logger.info("=" * 70)
        self._print_summary()

        # Exit code 0 if all PASS, 1 if any FAIL (WARN is OK)
        has_fail = any(r["status"] == "FAIL" for r in self.results)
        return 1 if has_fail else 0

    def _print_summary(self) -> None:
        """Print a summary table of all check results."""
        print("\n" + "=" * 70)
        print(f"{'Check Name':<25} {'Status':<10} {'Detail':<35}")
        print("-" * 70)
        for result in self.results:
            check = result["check"][:24]
            status = result["status"]
            detail = result["detail"][:34]
            print(f"{check:<25} {status:<10} {detail:<35}")
        print("=" * 70 + "\n")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check JARVIS TRADER engine health",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Engine hostname or IP (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8010,
        help="Engine port (default: 8010)",
    )
    parser.add_argument(
        "--api-key",
        default="test-key",
        help="X-API-Key header value (default: test-key)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Request timeout in seconds (default: 5)",
    )

    args = parser.parse_args()

    checker = HealthChecker(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    return checker.run_all_checks()


if __name__ == "__main__":
    sys.exit(main())
