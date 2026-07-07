#!/usr/bin/env python3
"""
Smoke Test for IB Gateway Paper E2E Validation (US-1408)

Exercises the JARVIS TRADER paper trading endpoints to verify the multi-market
framework, paper validation gates, scheduler, and IB Gateway connectivity are
working correctly before live paper trading begins.

Covers:
  - GET /health (engine is running)
  - GET /paper-validation/gates (validation gates array)
  - GET /scheduler/jobs (scheduled jobs are registered)
  - GET /ib/status (IB Gateway connection status, WARN if disconnected)
  - GET /paper/positions (open positions)
  - GET /scanner/signals/latest (latest scanner signals)
  - GET /paper-validation/wfe (walk-forward efficiency instruments)

Critical checks (exit 1 if fail):
  1. /health — engine up
  2. /paper-validation/gates — gates endpoint responds
  3. /scheduler/jobs — jobs endpoint responds, expected jobs present

Warning checks (print [WARN] but exit 0):
  4. /ib/status — IB Gateway disconnected is expected outside market hours
  5. /paper/positions — could be empty or error
  6. /scanner/signals/latest — scanner signals endpoint responds
  7. /paper-validation/wfe — WFE endpoint responds

Usage:
    cd engine
    .venv/Scripts/python ../scripts/smoke_test_paper_e2e.py

Environment:
    Requires API_KEY to be set in engine/.env
    Engine must be running on http://localhost:8010
"""

import logging
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERROR: python-dotenv not found. Install with: pip install python-dotenv")
    sys.exit(1)

import os


def setup_logging() -> logging.Logger:
    """Configure logging for smoke tests."""
    logger = logging.getLogger("smoke_test_paper_e2e")
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()


class PaperE2ESmokeTest:
    """Validates paper trading E2E endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 5):
        """Initialize smoke tester.

        Args:
            base_url: Engine base URL (e.g., http://localhost:8010)
            api_key: API key for X-API-Key header
            timeout: Request timeout in seconds
        """
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-API-Key": api_key}
        self.results = []
        self.critical_pass = 0
        self.critical_total = 0
        self.warnings = 0

    def _request(self, method: str, endpoint: str) -> tuple[bool, int, Any]:
        """Make HTTP request and return (success, status_code, response_data)."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            else:
                resp = requests.post(url, headers=self.headers, timeout=self.timeout)

            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text}

            return resp.status_code == 200, resp.status_code, data
        except requests.exceptions.ConnectionError:
            return False, 0, {"error": "Connection refused"}
        except requests.exceptions.Timeout:
            return False, 0, {"error": "Request timeout"}
        except requests.exceptions.RequestException as e:
            return False, 0, {"error": str(e)}

    def test_health(self) -> bool:
        """Test GET /health endpoint. CRITICAL."""
        logger.info("Testing GET /health...")
        success, status_code, data = self._request("GET", "/health")
        self.critical_total += 1

        if success:
            self._record("PASS", "GET /health", status_code, "engine running")
            self.critical_pass += 1
            return True
        else:
            self._record("FAIL", "GET /health", status_code, data.get("error"))
            return False

    def test_paper_validation_gates(self) -> bool:
        """Test GET /paper-validation/gates endpoint. CRITICAL."""
        logger.info("Testing GET /paper-validation/gates...")
        success, status_code, data = self._request("GET", "/paper-validation/gates")
        self.critical_total += 1

        if not success:
            self._record(
                "FAIL",
                "GET /paper-validation/gates",
                status_code,
                data.get("error"),
            )
            return False

        if "gates" not in data:
            self._record(
                "FAIL",
                "GET /paper-validation/gates",
                status_code,
                "Response missing 'gates' key",
            )
            return False

        gates_count = len(data.get("gates", []))
        self._record(
            "PASS",
            "GET /paper-validation/gates",
            status_code,
            f"{gates_count} gates",
        )
        self.critical_pass += 1
        return True

    def test_scheduler_jobs(self) -> bool:
        """Test GET /scheduler/jobs endpoint. CRITICAL."""
        logger.info("Testing GET /scheduler/jobs...")
        success, status_code, data = self._request("GET", "/scheduler/jobs")
        self.critical_total += 1

        if not success:
            self._record(
                "FAIL",
                "GET /scheduler/jobs",
                status_code,
                data.get("error"),
            )
            return False

        if "jobs" not in data:
            self._record(
                "FAIL",
                "GET /scheduler/jobs",
                status_code,
                "Response missing 'jobs' key",
            )
            return False

        jobs = data.get("jobs", [])
        job_names = [j.get("name") if isinstance(j, dict) else str(j) for j in jobs]
        jobs_count = len(jobs)

        required_jobs = {"market_open_scan", "eod_summary", "intraday_scan_15m"}
        found_jobs = set(job_names) & required_jobs

        if len(found_jobs) < len(required_jobs):
            missing = required_jobs - found_jobs
            self._record(
                "WARN",
                "GET /scheduler/jobs",
                status_code,
                f"{jobs_count} jobs (missing: {missing})",
            )
            self.warnings += 1
            return True

        self._record(
            "PASS",
            "GET /scheduler/jobs",
            status_code,
            f"{jobs_count} jobs registered",
        )
        self.critical_pass += 1
        return True

    def test_ib_status(self) -> bool:
        """Test GET /ib/status endpoint. WARNING only."""
        logger.info("Testing GET /ib/status...")
        success, status_code, data = self._request("GET", "/ib/status")

        if not success:
            self._record(
                "WARN",
                "GET /ib/status",
                status_code,
                f"endpoint error: {data.get('error')}",
            )
            self.warnings += 1
            return True

        connected = data.get("connected", False)
        if not connected:
            self._record(
                "WARN",
                "GET /ib/status",
                status_code,
                "IB Gateway disconnected (expected outside market hours)",
            )
            self.warnings += 1
        else:
            self._record(
                "PASS",
                "GET /ib/status",
                status_code,
                "IB Gateway connected",
            )

        return True

    def test_paper_positions(self) -> bool:
        """Test GET /paper/positions endpoint. WARNING only."""
        logger.info("Testing GET /paper/positions...")
        success, status_code, data = self._request("GET", "/paper/positions")

        if not success:
            self._record(
                "WARN",
                "GET /paper/positions",
                status_code,
                f"endpoint error: {data.get('error')}",
            )
            self.warnings += 1
            return True

        positions = data.get("positions", []) if isinstance(data, dict) else []
        pos_count = len(positions)
        self._record(
            "PASS",
            "GET /paper/positions",
            status_code,
            f"{pos_count} open positions",
        )
        return True

    def test_scanner_signals_latest(self) -> bool:
        """Test GET /scanner/signals/latest endpoint. WARNING only."""
        logger.info("Testing GET /scanner/signals/latest...")
        success, status_code, data = self._request("GET", "/scanner/signals/latest")

        if not success:
            self._record(
                "WARN",
                "GET /scanner/signals/latest",
                status_code,
                f"endpoint error: {data.get('error')}",
            )
            self.warnings += 1
            return True

        signals = data.get("signals", []) if isinstance(data, dict) else []
        sig_count = len(signals)
        self._record(
            "PASS",
            "GET /scanner/signals/latest",
            status_code,
            f"{sig_count} signals in buffer",
        )
        return True

    def test_paper_validation_wfe(self) -> bool:
        """Test GET /paper-validation/wfe endpoint. WARNING only."""
        logger.info("Testing GET /paper-validation/wfe...")
        success, status_code, data = self._request("GET", "/paper-validation/wfe")

        if not success:
            self._record(
                "WARN",
                "GET /paper-validation/wfe",
                status_code,
                f"endpoint error: {data.get('error')}",
            )
            self.warnings += 1
            return True

        instruments = data.get("instruments", []) if isinstance(data, dict) else []
        inst_count = len(instruments)
        self._record(
            "PASS",
            "GET /paper-validation/wfe",
            status_code,
            f"{inst_count} instruments",
        )
        return True

    def _record(
        self, status: str, endpoint: str, http_status: int, detail: str
    ) -> None:
        """Record a test result."""
        self.results.append(
            {
                "status": status,
                "endpoint": endpoint,
                "http_status": http_status,
                "detail": detail,
            }
        )
        logger.info(f"[{status}] {endpoint} (HTTP {http_status}): {detail}")

    def run_all_tests(self) -> int:
        """Run all paper E2E smoke tests. Return 0 if critical pass, 1 if critical fail."""
        logger.info(f"Starting paper E2E smoke tests of {self.base_url}")
        logger.info("=" * 80)

        tests = [
            ("Health Check", self.test_health, True),
            ("Paper Validation Gates", self.test_paper_validation_gates, True),
            ("Scheduler Jobs", self.test_scheduler_jobs, True),
            ("IB Gateway Status", self.test_ib_status, False),
            ("Paper Positions", self.test_paper_positions, False),
            ("Scanner Signals", self.test_scanner_signals_latest, False),
            ("Paper Validation WFE", self.test_paper_validation_wfe, False),
        ]

        for name, test_fn, is_critical in tests:
            try:
                test_fn()
            except Exception as e:
                logger.exception(f"Exception during {name}: {e}")
                self._record("FAIL" if is_critical else "WARN", name, 0, f"Exception: {e}")
                if is_critical:
                    self.critical_pass = max(0, self.critical_pass - 1)
                else:
                    self.warnings += 1

        logger.info("=" * 80)
        self._print_summary()

        return 0 if self.critical_pass == self.critical_total else 1

    def _print_summary(self) -> None:
        """Print a formatted summary of all test results."""
        print("\nJARVIS TRADER — Paper E2E Smoke Test")
        print("=" * 80)

        for result in self.results:
            status = result["status"]
            endpoint = result["endpoint"]
            http_status = result["http_status"]
            detail = result["detail"]
            print(f"[{status}] {endpoint} — {detail} ({http_status})")

        print("=" * 80)

        status_banner = (
            "READY FOR PAPER TRADING"
            if self.critical_pass == self.critical_total
            else "NOT READY"
        )
        print(f"RESULT: {status_banner}")
        print(f"Critical: {self.critical_pass}/{self.critical_total} pass | Warnings: {self.warnings}")
        print("=" * 80 + "\n")


def main() -> int:
    """Main entry point."""
    base_url = os.getenv("BASE_URL", "http://localhost:8010")
    timeout = 5

    env_file = Path(__file__).parent.parent / "engine" / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded .env from {env_file}")
    else:
        logger.warning(f".env not found at {env_file}")

    api_key = os.getenv("API_KEY") or os.getenv("JARVIS_API_KEY", "test-key")
    if api_key == "test-key":
        logger.warning("API_KEY not set in environment, using default 'test-key'")

    tester = PaperE2ESmokeTest(base_url=base_url, api_key=api_key, timeout=timeout)
    return tester.run_all_tests()


if __name__ == "__main__":
    sys.exit(main())
