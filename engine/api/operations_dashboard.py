"""
Operations Dashboard — FastAPI router.

Two endpoints:
  GET /operations/dashboard.json  — structured JSON for all panels
  GET /operations/dashboard.html  — serves the self-contained HTML page

No external dependencies beyond FastAPI + stdlib + the existing engine modules.
No writes; read-only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["operations", "dashboard"])

# ---------------------------------------------------------------------------
# Path constants (resolve relative to engine root regardless of CWD)
# ---------------------------------------------------------------------------

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ENGINE_ROOT / "data" / "jarvis_trader.db"
_PAPER_TRADES_JSON = _ENGINE_ROOT / "data" / "paper_trades.json"
_POST_TRADE_REPORTS_DIR = _ENGINE_ROOT / "data" / "post_trade_reports"
_LIVE_READINESS_REPORTS_DIR = _ENGINE_ROOT / "data" / "live_readiness_reports"
_DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "operations.html"
_ENGINE_HEALTH_URL = "http://127.0.0.1:8010/health"
_ENGINE_TIMEOUT_SEC = 4

# PnL daily target (matches the ROI readiness gate G1)
DAILY_PNL_TARGET = 250.0

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_et() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return datetime.utcnow().date()


def _trade_on_et_date(timestamp: Optional[str], target: date) -> bool:
    """True if a UTC-stamped trade timestamp falls on `target` in Eastern time.

    Trade timestamps are written in UTC (paper_trade_logger / IB fill_time use
    datetime.utcnow().isoformat()+"Z"). Comparing them to an ET date with a raw
    string startswith() silently dropped every evening trade: a 21:00 ET fill is
    01:00 UTC the NEXT day, so its "2026-06-07T01:00Z" stamp failed to match the
    ET day "2026-06-06" and vanished from the dashboard's daily P&L. Convert to ET
    before comparing the calendar date.
    """
    if not timestamp:
        return False
    try:
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).date() == target
    except Exception:
        # Last-resort fallback: naive prefix match (pre-fix behaviour).
        return timestamp.startswith(target.isoformat())


def _load_paper_trades_today(target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Load trades from paper_trades.json for the given date (default: today ET)."""
    if target_date is None:
        target_date = _today_et()
    if not _PAPER_TRADES_JSON.exists():
        return []
    try:
        data = json.loads(_PAPER_TRADES_JSON.read_text(encoding="utf-8"))
        trades = data if isinstance(data, list) else data.get("trades", [])
        return [
            t
            for t in trades
            if isinstance(t, dict) and _trade_on_et_date(t.get("timestamp"), target_date)
        ]
    except Exception as exc:
        logger.warning("paper_trades.json load failed: %s", exc)
        return []


def _compute_today_pnl(target_date: Optional[date] = None) -> Dict[str, Any]:
    """Use paper_trade_pairing helper for correct dollar PnL (multiplier applied)."""
    try:
        from analytics.paper_trade_pairing import compute_metrics, pair_trades

        trades = _load_paper_trades_today(target_date)
        closed = pair_trades(trades)
        metrics = compute_metrics(closed)
        return {
            "pnl": round(metrics["total_pnl"], 2),
            "total_trades": metrics["total_trades"],
            "wins": metrics["wins"],
            "losses": metrics["losses"],
            "win_rate": (
                round(metrics["win_rate"] * 100, 1) if metrics["win_rate"] is not None else None
            ),
            "source": "paper_trade_pairing",
        }
    except Exception as exc:
        logger.warning("PnL computation failed: %s", exc)
        return {
            "pnl": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "source": "error",
            "error": str(exc),
        }


def _get_open_positions_count() -> int:
    """Count open positions from SQLite paper_trades table."""
    if not _DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=5)
        try:
            row = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("open positions count failed: %s", exc)
        return 0


def _get_engine_health() -> Dict[str, Any]:
    """Hit /health and return a structured dict. Cached via module-level state."""
    try:
        resp = urlopen(_ENGINE_HEALTH_URL, timeout=_ENGINE_TIMEOUT_SEC)
        body = json.loads(resp.read().decode())
        return {
            "reachable": True,
            "status": body.get("status", "unknown"),
            "tradingview_mcp_healthy": body.get("tradingview_mcp_healthy", False),
            "llm_path_healthy": body.get("llm_path_healthy", False),
            "ibkr_exec": body.get("ibkr_execution_connected", False),
            "ibkr_data": body.get("ibkr_data_connected", False),
            "kill_switch_active": body.get("kill_switch_active", False),
            "polled_at": _utcnow(),
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status": "unreachable",
            "tradingview_mcp_healthy": False,
            "llm_path_healthy": False,
            "ibkr_exec": {"connected": False},
            "ibkr_data": {"connected": False},
            "kill_switch_active": False,
            "polled_at": _utcnow(),
            "error": str(exc),
        }


def _get_live_readiness() -> Dict[str, Any]:
    """Run ROI readiness gates and return summary. Falls back gracefully."""
    try:
        from backtest.roi_readiness import evaluate

        result = evaluate()
        gates = [
            {
                "gate_id": g.gate_id,
                "name": g.name,
                "passed": g.passed,
                "observed": g.observed,
                "threshold": g.threshold,
            }
            for g in result.gates
        ]
        return {
            "status": result.status,
            "pass_count": result.pass_count,
            "consecutive_passing_days": result.consecutive_passing_days,
            "days_to_live": result.days_to_live,
            "gates": gates,
            "source": "roi_readiness",
        }
    except Exception as exc:
        logger.warning("ROI readiness check failed: %s", exc)
        return {
            "status": "UNKNOWN",
            "pass_count": 0,
            "consecutive_passing_days": 0,
            "days_to_live": 14,
            "gates": [],
            "source": "error",
            "error": str(exc),
        }


def _get_uptime_7d() -> List[bool]:
    """
    Return a list of 7 booleans (oldest first) indicating engine snapshot
    presence for each of the last 7 calendar days.  True = snapshot present
    (engine was alive that day).

    Uses the LOCAL system date, matching how pnl_snapshots.date is actually
    written (risk/safety_layer.py's _persist_pnl_snapshot/_load_pnl_snapshot
    both key off date.today(), not UTC). Comparing against
    datetime.utcnow().date() made "today" read as DOWN for several hours
    after the local-midnight-UTC crossover (any evening, in a timezone
    behind UTC) even when the engine had genuinely written today's local
    snapshot, since this was looking for a row dated tomorrow (UTC) instead.
    """
    if not _DB_PATH.exists():
        return [False] * 7
    today = date.today()
    start = today - timedelta(days=6)
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=5)
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT date("date") AS d
                FROM pnl_snapshots
                WHERE date("date") >= ?
                """,
                (start.isoformat(),),
            ).fetchall()
            known_days = {r[0] for r in rows}
        finally:
            conn.close()
        result = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            result.append(day.isoformat() in known_days)
        return result
    except Exception:
        return [False] * 7


def _read_latest_report(reports_dir: Path, prefix: str = "") -> Optional[Dict[str, Any]]:
    """
    Find the most recent .md file in reports_dir (optionally filtered by prefix),
    return its path, date, and first 300 chars of content.
    """
    if not reports_dir.exists():
        return None
    try:
        files = sorted(
            [f for f in reports_dir.glob(f"{prefix}*.md") if f.is_file()],
            reverse=True,
        )
        if not files:
            return None
        latest = files[0]
        content = latest.read_text(encoding="utf-8", errors="replace")
        excerpt = content[:300].replace("\n", " ").strip()
        return {
            "path": str(latest),
            "filename": latest.name,
            "date": latest.stem[:10] if len(latest.stem) >= 10 else latest.stem,
            "excerpt": excerpt,
        }
    except Exception as exc:
        logger.warning("report read failed (%s): %s", reports_dir, exc)
        return None


def _get_career_ops_recap() -> Optional[Dict[str, Any]]:
    """Look for today's or yesterday's career-ops recap in common locations."""
    candidate_dirs = [
        Path("C:/Users/mattm/Code/career-ops/reports"),
        Path("C:/Users/mattm/career-ops/reports"),
    ]
    today = _today_et().isoformat()
    from datetime import timedelta

    yesterday = (_today_et() - timedelta(days=1)).isoformat()
    for d in candidate_dirs:
        if not d.exists():
            continue
        for day in [today, yesterday]:
            f = d / f"{day}.md"
            if f.exists():
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    return {
                        "path": str(f),
                        "filename": f.name,
                        "date": day,
                        "excerpt": content[:300].replace("\n", " ").strip(),
                    }
                except Exception:
                    continue
    return None


# ---------------------------------------------------------------------------
# Main data builder — callable from tests without HTTP
# ---------------------------------------------------------------------------


def build_dashboard_data(target_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Assemble all panel data. Safe to call without the engine running —
    individual sections degrade gracefully.
    """
    if target_date is None:
        target_date = _today_et()

    pnl = _compute_today_pnl(target_date)
    engine_health = _get_engine_health()
    live_readiness = _get_live_readiness()
    uptime_7d = _get_uptime_7d()
    open_positions = _get_open_positions_count()

    post_trade = _read_latest_report(_POST_TRADE_REPORTS_DIR)
    live_readiness_report = _read_latest_report(_LIVE_READINESS_REPORTS_DIR)
    career_recap = _get_career_ops_recap()

    # Flatten the 4 key health booleans for header widget consumption.
    # Values are None (unknown) when the engine is unreachable.
    def _health_bool(val: Any) -> Optional[bool]:
        """Coerce a health field to bool | None."""
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, dict):
            connected = val.get("connected")
            return bool(connected) if connected is not None else None
        return bool(val)

    _reachable = engine_health.get("reachable", False)
    health_widget: Dict[str, Optional[bool]] = {
        "tv_mcp_healthy": (
            _health_bool(engine_health.get("tradingview_mcp_healthy")) if _reachable else None
        ),
        "llm_path_healthy": (
            _health_bool(engine_health.get("llm_path_healthy")) if _reachable else None
        ),
        "ibkr_data_connected": _health_bool(engine_health.get("ibkr_data")) if _reachable else None,
        "ibkr_execution_connected": (
            _health_bool(engine_health.get("ibkr_exec")) if _reachable else None
        ),
    }

    return {
        "generated_at": _utcnow(),
        "report_date": target_date.isoformat(),
        "health": health_widget,
        "today": {
            "pnl": pnl["pnl"],
            "pnl_target": DAILY_PNL_TARGET,
            "pnl_pct": round(pnl["pnl"] / DAILY_PNL_TARGET * 100, 1),
            "total_trades": pnl["total_trades"],
            "wins": pnl["wins"],
            "losses": pnl["losses"],
            "win_rate": pnl["win_rate"],
            "open_positions": open_positions,
        },
        "live_readiness": live_readiness,
        "engine_health": engine_health,
        "uptime_7d": uptime_7d,
        "reports": {
            "morning_briefing": live_readiness_report,  # readiness report serves as morning state
            "post_trade": post_trade,
            "career_recap": career_recap,
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard.json")
def get_dashboard_json() -> Dict[str, Any]:
    """Return all dashboard panel data as JSON."""
    return build_dashboard_data()


@router.get("/dashboard.html", response_class=HTMLResponse)
def get_dashboard_html() -> HTMLResponse:
    """Serve the self-contained operations dashboard HTML page."""
    if _DASHBOARD_HTML.exists():
        return HTMLResponse(content=_DASHBOARD_HTML.read_text(encoding="utf-8"))
    # Fallback: redirect hint if file not found
    return HTMLResponse(
        content="<h1>operations.html not found</h1>"
        "<p>Expected at: engine/dashboard/operations.html</p>",
        status_code=404,
    )
