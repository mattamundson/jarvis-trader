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

DEFAULT_BASE = "http://127.0.0.1:8010"


def _api_key_for_probe() -> str:
    key = os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY")
    if not key:
        from pathlib import Path

        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key or "test-key"


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
    True when RL training endpoints are available.
    Guards RL-specific integration tests.

    RL routes live under the ``/strategies`` router prefix — see
    routers/strategies_router.py: APIRouter(prefix="/strategies"). Earlier
    probe versions hit ``/rl/health`` directly and always got 404, silently
    skipping all 12 RL integration tests even on a healthy engine.
    """
    if not jarvis_engine_ready(base):
        return False
    # timeout=10 (was 3) — under full-suite load the engine can take several
    # seconds to answer even a cheap dep-probe. 3s was causing ~54 RL tests
    # to skip en masse in full-suite runs while passing in isolation.
    st, data = _get_json(base, "/strategies/rl/health", timeout=10.0)
    return st == 200 and isinstance(data, dict)


def rl_evaluate_contract_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when RL evaluation endpoint is ready.
    Guards contract validation for RL endpoints.

    ``/strategies/rl/evaluate`` is POST-only, so a GET returns 405 when the
    route is mounted — 405 counts as "routed" for this probe.
    """
    if not jarvis_rl_integration_ready(base):
        return False
    st, data = _get_json(base, "/strategies/rl/evaluate", timeout=3.0)
    return st in (200, 400, 405, 422)  # Routed if method-allowed OR method-not-allowed
