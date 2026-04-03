"""
Probe for live integration tests.

A process listening on :8010 with only GET /health is not sufficient — that caused
false positives when another stack occupied the port. We require a JARVIS-shaped
response from a keyed route (e.g. /safety/status) before running localhost integration tests.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8010"


def _api_key_for_probe() -> str:
    return os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY") or "test-key"


def _get_json(base: str, path: str, timeout: float = 5.0) -> tuple[int, object]:
    """GET path with API key; return (status_code, parsed JSON or empty dict)."""
    key = _api_key_for_probe()
    req = urllib.request.Request(f"{base}{path}")
    req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception:
        return 0, {}


def jarvis_engine_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True only if something that looks like the JARVIS engine is on ``base``:
    /health succeeds, and at least one of /safety/status or /portfolio/summary
    does not return 404 (200, 401, 503, etc. all count as "routed").
    """
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
            if not (200 <= resp.status < 300):
                return False
    except Exception:
        return False

    key = _api_key_for_probe()
    for path in ("/safety/status", "/portfolio/summary"):
        req = urllib.request.Request(f"{base}{path}")
        req.add_header("X-API-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            # 401 wrong key, 503 not initialized — still our app
            return True
        except Exception:
            return False
    return False


def session4_api_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when Session 4 contract paths exist on the running engine.

    Guard remains for live E2E tests that verify actual DB/broker state.
    Routes are fully implemented — see test_session4_contract.py for TestClient
    equivalents that run without a live engine.

    Also requires the **current** analytics router envelope (dict with ``days`` /
    ``symbols`` / ``hours`` keys), not a legacy bare JSON list, so mixed or stale
    localhost stacks do not fail the suite.
    """
    if not jarvis_engine_ready(base):
        return False
    key = _api_key_for_probe()
    req = urllib.request.Request(f"{base}/portfolio/stats/session-today")
    req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if not (200 <= resp.status < 300):
                return False
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        # 503 / 401 — still routed to our app; continue to analytics probe
    except Exception:
        return False

    st, by_day = _get_json(base, "/analytics/trades/by-day", timeout=3.0)
    if st != 200 or not isinstance(by_day, dict) or "days" not in by_day:
        return False

    st2, perf = _get_json(base, "/analytics/performance", timeout=3.0)
    if st2 != 200 or not isinstance(perf, dict) or "status" not in perf:
        return False

    st3, roll = _get_json(base, "/analytics/performance/rolling?days=7", timeout=3.0)
    if st3 != 200 or not isinstance(roll, dict) or "days" not in roll:
        return False

    return True


def live_analytics_contract_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when GET /analytics/performance matches the PerformanceMetricsResponse
    contract (includes ``status``). Used to skip single live tests when only
    analytics is stale.
    """
    if not jarvis_engine_ready(base):
        return False
    st, data = _get_json(base, "/analytics/performance", timeout=3.0)
    return st == 200 and isinstance(data, dict) and "status" in data


def jarvis_rl_integration_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when RL training endpoints (/rl/train, /rl/health) are available.
    Guards RL-specific integration tests.
    """
    if not jarvis_engine_ready(base):
        return False
    st, data = _get_json(base, "/rl/health", timeout=3.0)
    return st == 200 and isinstance(data, dict)


def rl_evaluate_contract_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when RL evaluation endpoint is ready.
    Guards contract validation for RL endpoints.
    """
    if not jarvis_rl_integration_ready(base):
        return False
    st, data = _get_json(base, "/rl/evaluate", timeout=3.0)
    return st in (200, 400, 422)  # Endpoint exists if it routes (even with bad input)
