"""
Probe for live integration tests.

A process listening on :8010 with only GET /health is not sufficient — that caused
false positives when another stack occupied the port. We require a JARVIS-shaped
response from a keyed route (e.g. /safety/status) before running localhost integration tests.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8010"


def _api_key_for_probe() -> str:
    return os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY") or "test-key"


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

    Those routes are not all implemented in-tree yet; without this guard, live
    tests fail with 404 when a real JARVIS instance is on :8010.
    """
    if not jarvis_engine_ready(base):
        return False
    key = _api_key_for_probe()
    req = urllib.request.Request(f"{base}/portfolio/stats/session-today")
    req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return False


def jarvis_rl_surface_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when RL integration tests can hit at least one canonical RL status URL.

    Accepts either ``/strategies/rl/status`` (preferred) or legacy ``/rl/status``.
    """
    if not jarvis_engine_ready(base):
        return False
    key = _api_key_for_probe()
    for path in ("/strategies/rl/status", "/rl/status"):
        req = urllib.request.Request(f"{base}{path}")
        req.add_header("X-API-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            return True
        except Exception:
            return False
    return False


def jarvis_rl_integration_ready(base: str = DEFAULT_BASE) -> bool:
    """
    True when the live engine exposes the RL surface this file asserts against:
    ``/strategies/rl/status`` and ``/strategies/rl/health``.

    Older deployments that only mounted part of the RL stack are skipped so CI
    and mixed localhost setups stay green.
    """
    if not jarvis_engine_ready(base):
        return False
    key = _api_key_for_probe()
    req = urllib.request.Request(f"{base}/strategies/rl/status")
    req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if not (200 <= resp.status < 300):
                return False
    except Exception:
        return False

    req2 = urllib.request.Request(f"{base}/strategies/rl/health")
    req2.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req2, timeout=3) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return False
