"""Tests for anti-signal-leakage log sanitizer."""

import logging

import pytest

from security.log_sanitizer import (
    SENSITIVE_PATTERNS,
    SIGNAL_PATTERNS,
    SanitizingFormatter,
    install_sanitizing_formatter,
    sanitize_message,
)


def _fake_anthropic_key(suffix: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ") -> str:
    """Build a sanitizer test key without storing a scanner-matching literal."""
    return "sk-ant-" + suffix


class TestSanitizeMessage:
    def test_no_sensitive_data_unchanged(self):
        msg = "Normal log message with no sensitive data"
        assert sanitize_message(msg) == msg

    def test_anthropic_api_key_masked(self):
        msg = f"Using key {_fake_anthropic_key()}"
        result = sanitize_message(msg)
        assert "sk-ant-***" in result
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result

    def test_whatsapp_number_masked(self):
        msg = "Sending to whatsapp:+17634520414"
        result = sanitize_message(msg)
        assert "whatsapp:+***" in result
        assert "17634520414" not in result

    def test_long_signal_masked_with_sanitize_signals(self):
        msg = "Signal: LONG MES @ 5823.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_short_signal_masked_with_sanitize_signals(self):
        msg = "Signal: SHORT MNQ @ 19432.25"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_long_signal_not_masked_without_sanitize_signals(self):
        msg = "Signal: LONG MES @ 5823.50"
        result = sanitize_message(msg, sanitize_signals=False)
        # LONG keyword itself should still be present (entry/exit patterns only active with sanitize_signals=True)
        assert "LONG" in result

    def test_entry_price_masked_with_signals(self):
        msg = "Entry: 5823.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_stop_price_masked_with_signals(self):
        msg = "Stop: 5810.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_contracts_masked_with_signals(self):
        msg = "Placing 2 contracts MES"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "*** contracts" in result

    def test_pnl_masked_with_signals(self):
        msg = "Daily P&L: +$284.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "$***" in result or "+/-$***" in result

    def test_empty_string_unchanged(self):
        assert sanitize_message("") == ""

    def test_none_converted_to_string(self):
        result = sanitize_message(None)  # type: ignore
        assert isinstance(result, str)

    def test_twilio_account_sid_masked(self):
        msg = "Twilio SID: ACabcdef1234567890abcdef1234567890"
        result = sanitize_message(msg)
        assert "AC***" in result

    def test_ib_account_number_masked(self):
        msg = "IB account U123456 connected"
        result = sanitize_message(msg)
        assert "IB***" in result

    def test_does_not_crash_on_unicode(self):
        msg = "Unicode test: \u65e5\u672c\u8a9e \u30c6\u30b9\u30c8"
        result = sanitize_message(msg)
        assert isinstance(result, str)

    def test_multiple_api_keys_in_one_message(self):
        msg = (
            f"key1={_fake_anthropic_key('AAABBBCCCDDDEEEFFFGGGHHH')} "
            f"key2={_fake_anthropic_key('ZZZYYYXXXWWWVVV111222333')}"
        )
        result = sanitize_message(msg)
        assert "sk-ant-***" in result
        assert "AAABBBCCCDDDEEEFFFGGGHHH" not in result
        assert "ZZZYYYXXXWWWVVV" not in result

    def test_bearer_token_masked(self):
        msg = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = sanitize_message(msg)
        assert "Bearer ***" in result
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result

    def test_sk_proj_masked(self):
        msg = "key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcd"
        result = sanitize_message(msg)
        assert "sk-proj-***" in result
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcd" not in result

    def test_polygon_env_assignment_masked(self):
        msg = "POLYGON_API_KEY=abcdefghijklmnopqrstuvwxyz1234567890"
        result = sanitize_message(msg)
        assert "POLYGON_API_KEY=***" in result
        assert "abcdefghijklmnopqrstuvwxyz1234567890" not in result

    def test_signal_patterns_not_applied_by_default(self):
        msg = "Entry: 5000.00, Stop: 4900.00"
        result = sanitize_message(msg)
        # Without sanitize_signals=True, entry/stop should remain
        assert "5000.00" in result

    def test_signal_patterns_applied_when_requested(self):
        msg = "Entry: 5000.00, Stop: 4900.00"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "5000.00" not in result
        assert "4900.00" not in result

    def test_target_price_masked_with_signals(self):
        msg = "Target: 5900.00"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result
        assert "5900.00" not in result

    def test_return_type_always_string(self):
        for input_val in [None, 42, 3.14, [], {}]:
            result = sanitize_message(input_val)  # type: ignore
            assert isinstance(result, str), f"Expected str for input {input_val!r}"

    def test_whatsapp_international_number(self):
        msg = "Alert sent to whatsapp:+447911123456"
        result = sanitize_message(msg)
        assert "whatsapp:+***" in result
        assert "447911123456" not in result

    def test_sensitive_patterns_list_not_empty(self):
        assert len(SENSITIVE_PATTERNS) > 0

    def test_signal_patterns_list_not_empty(self):
        assert len(SIGNAL_PATTERNS) > 0


class TestSanitizingFormatter:
    def setup_method(self):
        self.formatter = SanitizingFormatter(
            fmt="%(levelname)s - %(message)s",
            sanitize_signals=True,
        )

    def test_formatter_is_logging_formatter(self):
        assert isinstance(self.formatter, logging.Formatter)

    def test_formats_normal_record(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "Normal message", (), None)
        result = self.formatter.format(record)
        assert "Normal message" in result

    def test_sanitizes_api_key_in_record(self):
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            f"Key: {_fake_anthropic_key()}",
            (),
            None,
        )
        result = self.formatter.format(record)
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result

    def test_never_crashes(self):
        """Formatter must never raise — log sanitization must be bulletproof."""
        record = logging.LogRecord("test", logging.ERROR, "", 0, None, (), None)
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised: {e}")

    def test_sanitize_signals_false_does_not_mask_prices(self):
        formatter = SanitizingFormatter(
            fmt="%(message)s",
            sanitize_signals=False,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "Entry: 5823.50", (), None)
        result = formatter.format(record)
        assert "5823.50" in result

    def test_sanitize_signals_true_masks_prices(self):
        formatter = SanitizingFormatter(
            fmt="%(message)s",
            sanitize_signals=True,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "Entry: 5823.50", (), None)
        result = formatter.format(record)
        assert "5823.50" not in result

    def test_formatter_with_dict_args(self):
        """Formatter should not crash when record.args is a dict."""
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            "key=%(key)s value=%(val)s",
            {"key": "[REDACTED_ANTHROPIC_KEY]", "val": "normal"},
            None,
        )
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised on dict args: {e}")

    def test_formatter_with_tuple_args(self):
        """Formatter should not crash when record.args is a tuple."""
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            "val=%s",
            ("[REDACTED_ANTHROPIC_KEY]",),
            None,
        )
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised on tuple args: {e}")


class TestInstallSanitizingFormatter:
    def test_install_does_not_crash(self):
        """Installing the formatter should not raise even if no handlers exist."""
        try:
            install_sanitizing_formatter(sanitize_signals=False)
        except Exception as e:
            pytest.fail(f"install_sanitizing_formatter raised: {e}")

    def test_install_with_signals_does_not_crash(self):
        """Installing with sanitize_signals=True should not raise."""
        try:
            install_sanitizing_formatter(sanitize_signals=True)
        except Exception as e:
            pytest.fail(f"install_sanitizing_formatter(sanitize_signals=True) raised: {e}")

    def test_install_idempotent(self):
        """Calling install multiple times should not cause errors."""
        try:
            install_sanitizing_formatter(sanitize_signals=False)
            install_sanitizing_formatter(sanitize_signals=True)
            install_sanitizing_formatter(sanitize_signals=False)
        except Exception as e:
            pytest.fail(f"Repeated install_sanitizing_formatter raised: {e}")
