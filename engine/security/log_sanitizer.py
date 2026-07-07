"""
Anti-signal-leakage log sanitizer.
Scrubs sensitive data from all log output when ENABLE_SIGNAL_SANITIZATION=True.
Inspired by Claude Code's signal sanitization pattern.
"""

import logging
import re
from typing import Optional

# Patterns that match sensitive data
SENSITIVE_PATTERNS = [
    # API keys (various formats) — longer / more specific first
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "sk-ant-***"),
    (re.compile(r"sk-proj-[A-Za-z0-9\-_]{20,}"), "sk-proj-***"),  # OpenAI project keys
    (re.compile(r"sk-[A-Za-z0-9]{40,}"), "sk-***"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]{20,}"), "Bearer ***"),
    (
        re.compile(
            r"(?i)(POLYGON_API_KEY|FINNHUB_API_KEY|ANTHROPIC_API_KEY|API_KEY)\s*=\s*([A-Za-z0-9_\-]{16,})"
        ),
        r"\1=***",
    ),
    (re.compile(r"AC[a-f0-9]{32}"), "AC***"),  # Twilio Account SID
    # Phone numbers (WhatsApp format)
    (re.compile(r"whatsapp:\+\d{10,15}"), "whatsapp:+***"),
    (re.compile(r"\+1\d{10}"), "+1***"),
    # IB account patterns
    (re.compile(r"\b[A-Z]{1}[0-9]{6}\b"), "IB***"),  # e.g. U123456
    # Futures prices (prevent signal leakage)
    (re.compile(r"LONG\s+[A-Z]{2,4}\s+@\s+[\d,]+\.?\d*"), "LONG *** @ ***"),
    (re.compile(r"SHORT\s+[A-Z]{2,4}\s+@\s+[\d,]+\.?\d*"), "SHORT *** @ ***"),
]

# These patterns are only applied when ENABLE_SIGNAL_SANITIZATION=True
SIGNAL_PATTERNS = [
    # Entry/exit prices
    (re.compile(r"entry[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "entry: ***"),
    (re.compile(r"stop[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "stop: ***"),
    (re.compile(r"target[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "target: ***"),
    # Position sizes
    (re.compile(r"\d+\s+contract[s]?", re.IGNORECASE), "*** contracts"),
    # P&L amounts
    (re.compile(r"[+-]\$[\d,]+\.?\d*"), "+/-$***"),
]


def sanitize_message(message: str, sanitize_signals: bool = False) -> str:
    """
    Apply sanitization patterns to a log message.

    Args:
        message: Raw log message
        sanitize_signals: If True, also sanitize trade signals and prices

    Returns:
        Sanitized message with sensitive data replaced
    """
    result = str(message)

    # Always apply API key / credential patterns
    for pattern, replacement in SENSITIVE_PATTERNS:
        if replacement is not None:
            result = pattern.sub(replacement, result)

    # Optionally apply signal patterns
    if sanitize_signals:
        for pattern, replacement in SIGNAL_PATTERNS:
            result = pattern.sub(replacement, result)

    return result


class SanitizingFormatter(logging.Formatter):
    """
    Custom logging formatter that sanitizes sensitive data from log records.
    Active when ENABLE_SIGNAL_SANITIZATION=True in config.
    """

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        sanitize_signals: bool = False,
    ):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.sanitize_signals = sanitize_signals

    def format(self, record: logging.LogRecord) -> str:
        # Format normally first
        formatted = super().format(record)
        # Then sanitize the fully-formatted string
        return sanitize_message(formatted, sanitize_signals=self.sanitize_signals)

    def formatMessage(self, record: logging.LogRecord) -> str:
        # Pre-format the message using original args (preserves %d, %f, etc.)
        # then sanitize the fully-interpolated string, clearing args to avoid
        # a second % interpolation by super().formatMessage() that would fail
        # if we had converted numeric args to strings.
        try:
            formatted_msg = record.getMessage()
        except Exception:
            formatted_msg = str(record.msg)
        sanitized_msg = sanitize_message(formatted_msg, sanitize_signals=self.sanitize_signals)
        record.msg = sanitized_msg
        record.args = None
        return super().formatMessage(record)


def install_sanitizing_formatter(sanitize_signals: bool = False) -> None:
    """
    Install the sanitizing formatter on the root logger and known sub-loggers.
    Should be called at startup when ENABLE_SIGNAL_SANITIZATION=True.

    Args:
        sanitize_signals: If True, trade signals and prices are also masked.
    """
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    sanitizing_formatter = SanitizingFormatter(fmt=fmt, sanitize_signals=sanitize_signals)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(sanitizing_formatter)

    # Also apply to the uvicorn loggers
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
        uvicorn_logger = logging.getLogger(logger_name)
        for handler in uvicorn_logger.handlers:
            handler.setFormatter(sanitizing_formatter)
