#!/usr/bin/env python3
"""
Smoke Test for Approval Flow (US-1301)

Exercises the JARVIS TRADER approval pipeline endpoints to verify Sprint 12
approval infrastructure is working correctly.

Covers:
  - GET /health (sanity check)
  - GET /pipeline/pending-approvals (list pending approvals)
  - GET /pipeline/pending-approvals?limit=5 (list with pagination)

Note: POST /pipeline/pending-approvals (insert mock) and approval/rejection
endpoints require a real pipeline run to generate a pending approval. This
script tests the list and query paths only.

Usage:
    cd engine
    .venv/Scripts/python ../scripts/smoke_test_approvals.py

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
    logger = logging.getLogger("smoke_test_approvals")
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()


class ApprovalSmokeTest:
    """Validates approval flow endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 5):
        """Initialize smoke tester.

        Args:
            base_url: Engine base URL (e.g., http://localhost:8010)
            api_key: X-API-Key header value
            timeout: Request timeout in seconds
        """
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-API-Key": api_key}
        self.results = []

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
        """Test GET /health endpoint."""
        logger.info("Testing GET /health...")
        success, status_code, data = self._request("GET", "/health")

        if success:
            self._record("PASS", "GET /health", status_code, "Engine is healthy")
            return True
        else:
            self._record("FAIL", "GET /health", status_code, data.get("error"))
            return False

    def test_pending_approvals_list(self) -> bool:
        """Test GET /pipeline/pending-approvals endpoint."""
        logger.info("Testing GET /pipeline/pending-approvals...")
        success, status_code, data = self._request("GET", "/pipeline/pending-approvals")

        if not success:
            self._record(
                "FAIL",
                "GET /pipeline/pending-approvals",
                status_code,
                data.get("error"),
            )
            return False

        if "pending" not in data:
            self._record(
                "FAIL",
                "GET /pipeline/pending-approvals",
                status_code,
                "Response missing 'pending' key",
            )
            return False

        pending_count = len(data.get("pending", []))
        self._record(
            "PASS",
            "GET /pipeline/pending-approvals",
            status_code,
            f"Found {pending_count} pending approval(s)",
        )
        return True

    def test_pending_approvals_with_limit(self) -> bool:
        """Test GET /pipeline/pending-approvals?limit=5 endpoint."""
        logger.info("Testing GET /pipeline/pending-approvals?limit=5...")
        success, status_code, data = self._request(
            "GET", "/pipeline/pending-approvals?limit=5"
        )

        if not success:
            self._record(
                "FAIL",
                "GET /pipeline/pending-approvals?limit=5",
                status_code,
                data.get("error"),
            )
            return False

        if "pending" not in data:
            self._record(
                "FAIL",
                "GET /pipeline/pending-approvals?limit=5",
                status_code,
                "Response missing 'pending' key",
            )
            return False

        pending_count = len(data.get("pending", []))
        self._record(
            "PASS",
            "GET /pipeline/pending-approvals?limit=5",
            status_code,
            f"Query returned {pending_count} approval(s) (limit=5)",
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
        """Run all approval smoke tests. Return 0 if all pass, 1 if any fail."""
        logger.info(f"Starting approval smoke tests of {self.base_url}")
        logger.info("=" * 80)

        tests = [
            ("Health Check", self.test_health),
            ("Pending Approvals List", self.test_pending_approvals_list),
            ("Pending Approvals with Limit", self.test_pending_approvals_with_limit),
        ]

        results = {}
        for name, test_fn in tests:
            try:
                results[name] = test_fn()
            except Exception as e:
                logger.exception(f"Exception during {name}: {e}")
                self._record("FAIL", name, 0, f"Exception: {e}")
                results[name] = False

        logger.info("=" * 80)
        self._print_summary()

        has_fail = any(r["status"] == "FAIL" for r in self.results)
        return 1 if has_fail else 0

    def _print_summary(self) -> None:
        """Print a summary table of all test results."""
        print("\n" + "=" * 80)
        print(
            f"{'Endpoint':<45} {'HTTP Status':<12} {'Result':<10} {'Detail':<13}"
        )
        print("-" * 80)
        for result in self.results:
            endpoint = result["endpoint"][:44]
            http_status = str(result["http_status"])[:11]
            status = result["status"]
            detail = result["detail"][:12]
            print(f"{endpoint:<45} {http_status:<12} {status:<10} {detail:<13}")
        print("=" * 80 + "\n")


def main() -> int:
    """Main entry point."""
    base_url = "http://localhost:8010"
    timeout = 5

    env_file = Path(__file__).parent.parent / "engine" / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded .env from {env_file}")
    else:
        logger.warning(f".env not found at {env_file}")

    api_key = os.getenv("API_KEY", "test-key")
    if api_key == "test-key":
        logger.warning("API_KEY not set in environment, using default 'test-key'")

    tester = ApprovalSmokeTest(base_url=base_url, api_key=api_key, timeout=timeout)
    return tester.run_all_tests()


if __name__ == "__main__":
    sys.exit(main())
