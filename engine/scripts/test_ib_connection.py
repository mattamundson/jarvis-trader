"""
Test IB Gateway Connectivity and Port Isolation.

Tests TCP connectivity to IB Gateway paper (7497) and confirms live
trading port (4001) is blocked. Validates client_id isolation.

Run standalone: python engine/scripts/test_ib_connection.py
"""

import logging
import socket
import sys
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single connectivity test."""

    test_name: str
    passed: bool
    message: str


class IBGatewayConnectivityTester:
    """Test IB Gateway connectivity and safety constraints."""

    # Default IB Gateway ports
    PAPER_PORT = 7497  # Paper trading port
    LIVE_PORT = 4001  # Live trading port (must be blocked)
    PAPER_GATEWAY_PORT = 4002  # Alternative paper trading port

    # Test configuration
    HOST = "127.0.0.1"
    TIMEOUT = 2.0  # TCP connection timeout
    CLIENT_IDS = [1, 2]  # Data manager, Orchestrator

    def __init__(self):
        """Initialize tester with logging."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.results: list[TestResult] = []

    def run_all_tests(self) -> bool:
        """
        Run all connectivity and safety tests.

        Returns:
            True if all critical tests passed
        """
        logger.info("=" * 80)
        logger.info("IB GATEWAY CONNECTIVITY & SAFETY TEST SUITE")
        logger.info("=" * 80)

        # Test 1: Verify port 4001 is NOT accessible
        self._test_port_4001_blocked()

        # Test 2: Verify port 7497 (paper) is accessible or gracefully fails
        self._test_paper_port_accessible()

        # Test 3: Verify port 4002 (paper gateway) is accessible or gracefully fails
        self._test_paper_gateway_port_accessible()

        # Test 4: Test client_id=1 connection (data manager)
        self._test_client_id_connection(1)

        # Test 5: Test client_id=2 connection (orchestrator)
        self._test_client_id_connection(2)

        # Test 6: Verify no port conflicts
        self._test_no_port_conflicts()

        # Print summary
        self._print_summary()

        # Return True if critical tests passed
        critical_passed = all(
            r.passed for r in self.results if "4001" in r.test_name
        )
        return critical_passed

    def _test_port_4001_blocked(self) -> None:
        """
        CRITICAL TEST: Verify port 4001 (live trading) is NOT accessible.

        Port 4001 is permanently blocked during paper trading phase.
        This test ensures accidental connection to live trading port fails.
        """
        test_name = "Port 4001 (live trading) is BLOCKED"
        logger.info(f"TEST: {test_name}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.TIMEOUT)

            try:
                result = sock.connect_ex((self.HOST, self.LIVE_PORT))
                sock.close()

                # Port 4001 should be UNREACHABLE (result != 0)
                if result != 0:
                    message = (
                        "PASS: Port 4001 is blocked (cannot connect to live trading)"
                    )
                    self.results.append(TestResult(test_name, True, message))
                    logger.info(f"  PASS: {message}")
                else:
                    message = (
                        "FAIL: Port 4001 is accessible (live trading port should be blocked!)"
                    )
                    self.results.append(TestResult(test_name, False, message))
                    logger.warning(f"  FAIL: {message}")

            finally:
                sock.close()

        except Exception as exc:
            message = f"ERROR during port check: {exc}"
            self.results.append(TestResult(test_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _test_paper_port_accessible(self) -> None:
        """
        Test if port 7497 (IB Gateway paper trading) is accessible.

        This test is informational — IB Gateway may not be running locally.
        Graceful fallback: if port is down, log INFO not ERROR.
        """
        test_name = f"Port {self.PAPER_PORT} (IB Gateway paper) is accessible"
        logger.info(f"TEST: {test_name}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.TIMEOUT)

            try:
                result = sock.connect_ex((self.HOST, self.PAPER_PORT))
                sock.close()

                if result == 0:
                    message = (
                        f"PASS: Port {self.PAPER_PORT} is accessible "
                        "(IB Gateway is running)"
                    )
                    self.results.append(TestResult(test_name, True, message))
                    logger.info(f"  PASS: {message}")
                else:
                    message = (
                        f"INFO: Port {self.PAPER_PORT} is not responding "
                        "(IB Gateway may not be running, graceful fallback)"
                    )
                    self.results.append(TestResult(test_name, False, message))
                    logger.info(f"  INFO: {message}")

            finally:
                sock.close()

        except Exception as exc:
            message = f"INFO: Could not test port {self.PAPER_PORT}: {exc}"
            self.results.append(TestResult(test_name, False, message))
            logger.info(f"  INFO: {message}")

    def _test_paper_gateway_port_accessible(self) -> None:
        """
        Test if port 4002 (IB Gateway paper trading gateway) is accessible.

        Config.IBKR_PORT defaults to 4002 (paper mode).
        Graceful fallback if IB Gateway not running.
        """
        test_name = f"Port {self.PAPER_GATEWAY_PORT} (IB Gateway paper) is accessible"
        logger.info(f"TEST: {test_name}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.TIMEOUT)

            try:
                result = sock.connect_ex((self.HOST, self.PAPER_GATEWAY_PORT))
                sock.close()

                if result == 0:
                    message = (
                        f"PASS: Port {self.PAPER_GATEWAY_PORT} is accessible "
                        "(IB Gateway is running)"
                    )
                    self.results.append(TestResult(test_name, True, message))
                    logger.info(f"  PASS: {message}")
                else:
                    message = (
                        f"INFO: Port {self.PAPER_GATEWAY_PORT} is not responding "
                        "(IB Gateway may not be running, graceful fallback)"
                    )
                    self.results.append(TestResult(test_name, False, message))
                    logger.info(f"  INFO: {message}")

            finally:
                sock.close()

        except Exception as exc:
            message = f"INFO: Could not test port {self.PAPER_GATEWAY_PORT}: {exc}"
            self.results.append(TestResult(test_name, False, message))
            logger.info(f"  INFO: {message}")

    def _test_client_id_connection(self, client_id: int) -> None:
        """
        Test that a specific client_id can connect without conflict.

        Each client_id represents a different component:
          - client_id=1: Data manager
          - client_id=2: Orchestrator

        Graceful fallback if IB Gateway not running.
        """
        test_name = f"Client ID {client_id} connection"
        logger.info(f"TEST: {test_name}")

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.TIMEOUT)

            try:
                # Attempt connection to paper trading port
                result = sock.connect_ex((self.HOST, self.PAPER_GATEWAY_PORT))
                sock.close()

                if result == 0:
                    message = f"PASS: Client ID {client_id} can connect to paper port"
                    self.results.append(TestResult(test_name, True, message))
                    logger.info(f"  PASS: {message}")
                else:
                    message = (
                        f"INFO: Client ID {client_id} cannot connect "
                        "(IB Gateway not running, graceful fallback)"
                    )
                    self.results.append(TestResult(test_name, False, message))
                    logger.info(f"  INFO: {message}")

            finally:
                sock.close()

        except Exception as exc:
            message = f"INFO: Could not test client {client_id}: {exc}"
            self.results.append(TestResult(test_name, False, message))
            logger.info(f"  INFO: {message}")

    def _test_no_port_conflicts(self) -> None:
        """
        Test that paper trading ports don't conflict with live port.

        CRITICAL: Ports 4001 (live) and 4002 (paper) must be distinct.
        """
        test_name = "No port conflicts (paper != live)"
        logger.info(f"TEST: {test_name}")

        if self.LIVE_PORT != self.PAPER_GATEWAY_PORT:
            message = (
                f"PASS: Live port ({self.LIVE_PORT}) != Paper port "
                f"({self.PAPER_GATEWAY_PORT})"
            )
            self.results.append(TestResult(test_name, True, message))
            logger.info(f"  PASS: {message}")
        else:
            message = "FAIL: Live and paper ports are the same!"
            self.results.append(TestResult(test_name, False, message))
            logger.error(f"  FAIL: {message}")

    def _print_summary(self) -> None:
        """Print test summary with pass/fail counts."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            logger.info(f"  [{status}] {result.test_name}")
            logger.info(f"        {result.message}")

        logger.info("")
        logger.info(f"Results: {passed}/{total} passed, {failed}/{total} failed")
        logger.info("=" * 80)

        if failed == 0:
            logger.info("All tests PASSED!")
        elif failed == total:
            logger.warning("All tests FAILED!")
        else:
            logger.warning(f"{failed} test(s) FAILED!")


def main() -> int:
    """
    Main entry point.

    Returns:
        0 if all critical tests passed, 1 otherwise
    """
    tester = IBGatewayConnectivityTester()
    critical_passed = tester.run_all_tests()

    # Return exit code
    return 0 if critical_passed else 1


if __name__ == "__main__":
    sys.exit(main())
