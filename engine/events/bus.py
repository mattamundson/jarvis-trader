from collections import deque
from datetime import datetime
from uuid import uuid4

import pytz

_events: deque = deque(maxlen=150)
_last_regime: dict[str, str] = {}

# Central timezone for logging
_CT = pytz.timezone("America/Chicago")


def publish(type: str, message: str, symbol: str | None = None, severity: str = "info") -> None:
    """Publish an event to the ring buffer.

    Args:
        type: Event type (pipeline_run, trade_opened, trade_closed, signal_fired, regime_change, system, etc.)
        message: Human-readable event description
        symbol: Optional symbol (MES, MNQ, MCL, etc.)
        severity: One of 'info', 'warn', 'critical'
    """
    event = {
        "id": uuid4().hex,
        "type": type,
        "symbol": symbol,
        "message": message,
        "severity": severity,
        "timestamp": datetime.now(_CT).isoformat(),
    }
    _events.append(event)


def get_recent(limit: int = 20) -> list[dict]:
    """Get recent events in newest-first order.

    Args:
        limit: Maximum number of events to return (capped at buffer size)

    Returns:
        List of event dicts, newest first
    """
    return list(reversed(list(_events)))[:limit]


def detect_regime_change(symbol: str, new_regime: str) -> str | None:
    """Detect if regime changed for a symbol.

    Returns:
        Old regime string if changed, None if unchanged or first occurrence
    """
    old_regime = _last_regime.get(symbol)
    _last_regime[symbol] = new_regime

    if old_regime is None or old_regime == new_regime:
        return None
    return old_regime
