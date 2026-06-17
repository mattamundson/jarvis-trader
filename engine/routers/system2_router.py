"""system2_router.py — System 2 ES/NQ executor status endpoint."""
from fastapi import APIRouter
from pathlib import Path
import json
from datetime import datetime, timezone

router = APIRouter(prefix="/system2", tags=["system2"])

_BASE = Path(__file__).parent.parent / "system2"
_HEARTBEAT = _BASE / "state" / "heartbeat.json"
_TRADES = _BASE / "logs" / "system2_trades.jsonl"

_STALE_SECONDS = 60  # heartbeat older than 60s → not running


def _read_heartbeat() -> dict | None:
    try:
        if _HEARTBEAT.exists():
            return json.loads(_HEARTBEAT.read_text())
    except Exception:
        pass
    return None


def _read_trades(limit: int = 20) -> list[dict]:
    try:
        if not _TRADES.exists():
            return []
        lines = _TRADES.read_text().strip().splitlines()
        trades = []
        for line in lines:
            try:
                trades.append(json.loads(line))
            except Exception:
                continue
        return trades[-limit:]
    except Exception:
        return []


@router.get("/status")
async def system2_status():
    """
    Return executor running state, last heartbeat, recent trades, and last signal.
    Reads from filesystem state files — no IBKR connection required.
    """
    hb = _read_heartbeat()
    trades = _read_trades(20)

    running = False
    last_heartbeat = None
    pid = None
    port = None
    mode = "paper"

    if hb:
        last_heartbeat = hb.get("ts")
        pid = hb.get("pid")
        port = hb.get("port")
        mode = "paper" if port == 4002 else "live"
        # Check staleness
        try:
            hb_dt = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            running = age < _STALE_SECONDS
        except Exception:
            running = False

    # Last signal = most recent SIGNAL event
    signals = [t for t in trades if t.get("event") == "SIGNAL"]
    last_signal = signals[-1] if signals else None

    return {
        "running": running,
        "mode": mode,
        "last_heartbeat": last_heartbeat,
        "pid": pid,
        "port": port,
        "recent_trades": trades,
        "last_signal": last_signal,
    }
