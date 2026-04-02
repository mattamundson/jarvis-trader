"""
Test Paper Trading Mode Safety Configuration.

Verifies that paper trading safety constraints are properly configured:
  - PAPER_TRADING = True
  - LIVE_TRADING_ENABLED = False
  - REQUIRE_HUMAN_APPROVAL = True
  - Kill switch thresholds (-2% daily, -10% drawdown)
  - Port 4001 (live trading) is blocked in code
  - IBGatewayConnector behavior in paper mode

Run standalone: python engine/scripts/test_paper_mode.py
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SafetyCheckResult:
    """Result of a safety configuration check."""

    check_name: str
    passed: bool
    message: str
    details: str = ""


class PaperModeSafetyTester:
    """Verify paper trading mode safety configuration."""

    def __init__(self):
        """Initialize tester with logging."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.results: list[SafetyCheckResult] = []
        self.engine_dir = Path(__file__).parent.parent

    def run_all_checks(self) -> bool:
        """
        Run all paper trading safety checks.

        Returns:
            True if all critical checks passed
        """
        logger.info("=" * 80)
        logger.info("PAPER TRADING MODE SAFETY TEST SUITE")
        logger.info("=" * 80)

        # Check 1: Import config and verify PAPER_TRADING
        self._check_paper_trading_enabled()

        # Check 2: Verify LIVE_TRADING_ENABLED = False
        self._check_live_trading_disabled()

        # Check 3: Verify REQUIRE_HUMAN_APPROVAL = True
        self._check_human_approval_required()

        # Check 4: Verify kill switch thresholds
        self._check_kill_switch_thresholds()

        # Check 5: Search code for port 4001 blocking
        self._check_port_4001_blocked_in_code()

        # Check 6: Test IBGatewayConnector in paper mode
        self._test_ib_gateway_paper_mode()

        # Print summary
        self._print_summary()

        # Return True if all critical checks passed
        critical_passed = all(
            r.passed
            for r in self.results
            if any(
                x in r.check_name
                for x in ["PAPER_TRADING", "LIVE_TRADING", "Human Approval"]
            )
        )
        return critical_passed

    def _check_paper_trading_enabled(self) -> None:
        """Verify PAPER_TRADING = True in config."""
        check_name = "Config: PAPER_TRADING = True"
        logger.info(f"CHECK: {check_name}")

        try:
            # Try importing config
            sys.path.insert(0, str(self.engine_dir))

            from config import settings

            if settings.PAPER_TRADING is True:
                message = "PASS: PAPER_TRADING = True"
                details = (
                    f"Orders will be logged to JSON, not sent to broker. "
                    f"Broker: {settings.PAPER_TRADING_BROKER}"
                )
                self.results.append(SafetyCheckResult(check_name, True, message, details))
                logger.info(f"  PASS: {message}")
                logger.info(f"  Details: {details}")
            else:
                message = f"FAIL: PAPER_TRADING = {settings.PAPER_TRADING} (must be True)"
                self.results.append(SafetyCheckResult(check_name, False, message))
                logger.error(f"  FAIL: {message}")

        except Exception as exc:
            message = f"ERROR: Could not import config: {exc}"
            details = "Make sure .env is configured and engine/.venv is active"
            self.results.append(SafetyCheckResult(check_name, False, message, details))
            logger.error(f"  ERROR: {message}")
            logger.error(f"  Details: {details}")

    def _check_live_trading_disabled(self) -> None:
        """Verify LIVE_TRADING_ENABLED = False in config."""
        check_name = "Config: LIVE_TRADING_ENABLED = False"
        logger.info(f"CHECK: {check_name}")

        try:
            from config import settings

            if settings.LIVE_TRADING_ENABLED is False:
                message = "PASS: LIVE_TRADING_ENABLED = False (paper mode enforced)"
                details = (
                    "Live trading is disabled. No real orders can be sent "
                    "during paper testing phase."
                )
                self.results.append(SafetyCheckResult(check_name, True, message, details))
                logger.info(f"  PASS: {message}")
                logger.info(f"  Details: {details}")
            else:
                message = f"FAIL: LIVE_TRADING_ENABLED = {settings.LIVE_TRADING_ENABLED} (must be False)"
                self.results.append(SafetyCheckResult(check_name, False, message))
                logger.error(f"  FAIL: {message}")

        except Exception as exc:
            message = f"ERROR: Could not import config: {exc}"
            self.results.append(SafetyCheckResult(check_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _check_human_approval_required(self) -> None:
        """Verify REQUIRE_HUMAN_APPROVAL = True in config."""
        check_name = "Config: REQUIRE_HUMAN_APPROVAL = True"
        logger.info(f"CHECK: {check_name}")

        try:
            from config import settings

            if settings.REQUIRE_HUMAN_APPROVAL is True:
                message = "PASS: REQUIRE_HUMAN_APPROVAL = True"
                details = (
                    "Every trade requires human review before execution. "
                    "Automated execution is disabled."
                )
                self.results.append(SafetyCheckResult(check_name, True, message, details))
                logger.info(f"  PASS: {message}")
                logger.info(f"  Details: {details}")
            else:
                message = f"FAIL: REQUIRE_HUMAN_APPROVAL = {settings.REQUIRE_HUMAN_APPROVAL} (must be True)"
                self.results.append(SafetyCheckResult(check_name, False, message))
                logger.error(f"  FAIL: {message}")

        except Exception as exc:
            message = f"ERROR: Could not import config: {exc}"
            self.results.append(SafetyCheckResult(check_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _check_kill_switch_thresholds(self) -> None:
        """Verify kill switch thresholds (-2% daily, -10% drawdown)."""
        check_name = "Config: Kill switch thresholds"
        logger.info(f"CHECK: {check_name}")

        try:
            from config import settings

            daily_loss_pct = settings.MAX_DAILY_LOSS_PCT
            drawdown_pct = settings.MAX_DRAWDOWN_PCT

            # Expected values per safety.md
            expected_daily = 0.02  # -2%
            expected_drawdown = 0.10  # -10%

            all_correct = daily_loss_pct == expected_daily and drawdown_pct == expected_drawdown

            if all_correct:
                message = "PASS: Kill switch thresholds are correct"
                details = (
                    f"Daily loss halt: {daily_loss_pct:.1%} (expected {expected_daily:.1%}) | "
                    f"Drawdown halt: {drawdown_pct:.1%} (expected {expected_drawdown:.1%})"
                )
                self.results.append(SafetyCheckResult(check_name, True, message, details))
                logger.info(f"  PASS: {message}")
                logger.info(f"  Details: {details}")
            else:
                message = "FAIL: Kill switch thresholds mismatch"
                details = (
                    f"Daily loss: {daily_loss_pct:.1%} (expected {expected_daily:.1%}) | "
                    f"Drawdown: {drawdown_pct:.1%} (expected {expected_drawdown:.1%})"
                )
                self.results.append(SafetyCheckResult(check_name, False, message, details))
                logger.error(f"  FAIL: {message}")
                logger.error(f"  Details: {details}")

        except Exception as exc:
            message = f"ERROR: Could not read kill switch thresholds: {exc}"
            self.results.append(SafetyCheckResult(check_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _check_port_4001_blocked_in_code(self) -> None:
        """Search code for port 4001 blocking or protection."""
        check_name = "Code: Port 4001 (live trading) is blocked"
        logger.info(f"CHECK: {check_name}")

        try:
            # Search for port 4001 references in critical files
            critical_files = [
                self.engine_dir / "config.py",
                self.engine_dir / "execution" / "ib_gateway_connector.py",
                self.engine_dir / "main.py",
            ]

            found_blocking = False
            details_parts = []

            for file_path in critical_files:
                if not file_path.exists():
                    continue

                with open(file_path, "r") as f:
                    content = f.read()

                    # Look for explicit port 4001 references or blocking logic
                    if "4001" in content:
                        if any(
                            x in content
                            for x in [
                                "LIVE_TRADING_ENABLED",
                                "raise NotImplementedError",
                                "paper",
                            ]
                        ):
                            found_blocking = True
                            details_parts.append(
                                f"Found port safety logic in {file_path.name}"
                            )

            # Also check IB Gateway connector for live mode guard
            ib_connector = self.engine_dir / "execution" / "ib_gateway_connector.py"
            if ib_connector.exists():
                with open(ib_connector, "r") as f:
                    content = f.read()
                    if "NotImplementedError" in content and "live connection" in content:
                        found_blocking = True
                        details_parts.append(
                            "IBGatewayConnector raises NotImplementedError for live mode"
                        )

            if found_blocking:
                message = "PASS: Port 4001 has protection in code"
                details = " | ".join(details_parts) if details_parts else "Found blocking logic"
                self.results.append(SafetyCheckResult(check_name, True, message, details))
                logger.info(f"  PASS: {message}")
                logger.info(f"  Details: {details}")
            else:
                message = "WARNING: Could not verify port 4001 blocking in code"
                details = "Manual code review recommended"
                self.results.append(
                    SafetyCheckResult(check_name, False, message, details)
                )
                logger.warning(f"  WARNING: {message}")
                logger.warning(f"  Details: {details}")

        except Exception as exc:
            message = f"ERROR: Could not search code for port blocking: {exc}"
            self.results.append(SafetyCheckResult(check_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _test_ib_gateway_paper_mode(self) -> None:
        """Test IBGatewayConnector paper mode behavior."""
        check_name = "IBGatewayConnector: Paper mode behavior"
        logger.info(f"CHECK: {check_name}")

        try:
            from config import settings

            # Only test if PAPER_TRADING is True
            if not settings.PAPER_TRADING:
                message = "SKIPPED: PAPER_TRADING is False"
                self.results.append(SafetyCheckResult(check_name, False, message))
                logger.info(f"  SKIPPED: {message}")
                return

            from execution.ib_gateway_connector import IBGatewayConnector

            # Create a mock safety layer
            class MockSafetyLayer:
                """Mock safety layer that always approves orders."""

                def check_order(self, order_req, equity):
                    """Return approved order check result for testing."""
                    from risk.safety_layer import RiskCheckResult

                    return RiskCheckResult(approved=True)

            try:
                # Test instantiation
                connector = IBGatewayConnector(settings, MockSafetyLayer())

                # Test paper mode connect
                async def test_async():
                    result = await connector.connect()
                    return result

                # Run async test
                result = asyncio.run(test_async())

                if result is True:
                    message = "PASS: IBGatewayConnector.connect() succeeds in paper mode"
                    details = "Paper trade logger initialized successfully"
                    self.results.append(SafetyCheckResult(check_name, True, message, details))
                    logger.info(f"  PASS: {message}")
                    logger.info(f"  Details: {details}")
                else:
                    message = "FAIL: IBGatewayConnector.connect() returned False"
                    self.results.append(SafetyCheckResult(check_name, False, message))
                    logger.error(f"  FAIL: {message}")

            except ImportError as ie:
                message = f"INFO: Could not import IBGatewayConnector: {ie}"
                details = "ib_insync or PaperTradeLogger may not be available"
                self.results.append(SafetyCheckResult(check_name, False, message, details))
                logger.info(f"  INFO: {message}")

        except Exception as exc:
            message = f"ERROR: IBGatewayConnector test failed: {exc}"
            self.results.append(SafetyCheckResult(check_name, False, message))
            logger.error(f"  ERROR: {message}")

    def _print_summary(self) -> None:
        """Print safety verification report."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("SAFETY VERIFICATION REPORT")
        logger.info("=" * 80)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        logger.info("")
        logger.info("CRITICAL CHECKS:")
        logger.info("-" * 80)

        critical_names = ["PAPER_TRADING", "LIVE_TRADING", "Human Approval"]
        for result in self.results:
            if any(x in result.check_name for x in critical_names):
                status = "PASS" if result.passed else "FAIL"
                logger.info(f"  [{status}] {result.check_name}")
                logger.info(f"        {result.message}")
                if result.details:
                    logger.info(f"        {result.details}")

        logger.info("")
        logger.info("ALL CHECKS:")
        logger.info("-" * 80)

        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            logger.info(f"  [{status}] {result.check_name}")
            logger.info(f"        {result.message}")
            if result.details:
                logger.info(f"        {result.details}")

        logger.info("")
        logger.info(f"Results: {passed}/{total} passed, {failed}/{total} failed")
        logger.info("=" * 80)

        if failed == 0:
            logger.info("All safety checks PASSED!")
        else:
            logger.warning(f"{failed} check(s) FAILED or SKIPPED!")


def main() -> int:
    """
    Main entry point.

    Returns:
        0 if all critical safety checks passed, 1 otherwise
    """
    tester = PaperModeSafetyTester()
    critical_passed = tester.run_all_checks()

    # Return exit code
    return 0 if critical_passed else 1


if __name__ == "__main__":
    sys.exit(main())
