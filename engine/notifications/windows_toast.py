"""
Windows desktop toast notifications for JARVIS signals.
========================================================

Pops a native Windows 10/11 toast when a tradeable signal fires, so the user
gets a desktop notification on the machine even with the dashboard closed.

Backend: ``winotify`` (pure-Python, no compiled deps; spawns a short PowerShell
snippet to raise the toast). Add ``winotify`` to ``requirements-core.txt`` and
``pip install`` it in the engine venv. If the package is absent or the platform
is not Windows, this module degrades to a silent no-op — it never raises.

Enablement: opt-in via ``WINDOWS_TOAST_ENABLED`` (default OFF until verified).
Set ``WINDOWS_TOAST_ENABLED=1`` in ``engine/.env`` and restart the engine.

ASCII-only text is used in the toast body to avoid PowerShell 5.1 mojibake
(see ~/.claude/rules/windows-pitfalls.md).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

_APP_ID = "JARVIS TRADER"


def enabled() -> bool:
    """True only when explicitly enabled, on Windows, with winotify importable."""
    if os.getenv("WINDOWS_TOAST_ENABLED", "0").lower() not in ("1", "true", "yes", "on"):
        return False
    if not sys.platform.startswith("win"):
        return False
    try:
        import winotify  # noqa: F401
    except Exception:
        logger.warning(
            "WINDOWS_TOAST_ENABLED is set but 'winotify' is not installed — "
            "run: engine/.venv/Scripts/python -m pip install winotify"
        )
        return False
    return True


def _show_toast_sync(title: str, body: str) -> bool:
    """Blocking toast call — run in a thread so we never block the event loop."""
    try:
        from winotify import Notification

        toast = Notification(
            app_id=_APP_ID,
            title=title,
            msg=body,
        )
        toast.show()
        return True
    except Exception as exc:
        logger.warning("Windows toast show() failed: %s", exc)
        return False


def _ascii(text: str) -> str:
    """Strip non-ASCII so PS 5.1 never mangles the toast text."""
    return text.encode("ascii", "ignore").decode("ascii")


async def notify_signal(symbol: str, label: str, confidence: float, body: str) -> bool:
    """Show a signal toast. Returns True on success; never raises."""
    if not enabled():
        return False
    title = _ascii(f"JARVIS {label}: {symbol}  ({confidence:.0%})")
    msg = _ascii(body)
    try:
        return await asyncio.to_thread(_show_toast_sync, title, msg)
    except Exception as exc:
        logger.warning("Windows toast dispatch failed for %s: %s", symbol, exc)
        return False
