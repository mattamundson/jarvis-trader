"""
Unit tests — /health ibgateway_alive probe (Initiative 1, Track B3).

Verifies the port-liveness probe and its 30s cache without a running engine:
binds a real ephemeral listener on 127.0.0.1 to exercise the alive=True path,
and a known-closed port for alive=False. settings is monkeypatched to a tiny
namespace so the probe targets our controlled port, not the real IB port.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_ibgateway_alive.py -q
"""

import os
import pathlib
import socket
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
# health_router imports config.settings, which requires API_KEY. Under pytest the
# tests/conftest.py forces it from engine/.env first; this setdefault keeps the
# module importable when run standalone (it's a no-op once conftest has set it).
os.environ.setdefault("API_KEY", "test-key")

import routers.health_router as hr  # noqa: E402


def _reset_cache():
    hr._ibgw_health_cache.update(checked_at=0.0, alive=False, port=None)


def test_alive_true_when_port_listening():
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = lsock.getsockname()[1]
    hr.settings = SimpleNamespace(IBKR_PORT=port)
    _reset_cache()
    try:
        alive, p = hr._check_ibgateway_alive()
        assert alive is True
        assert p == port
    finally:
        lsock.close()


def test_alive_false_when_port_closed():
    # Bind then immediately close to obtain a port that is now free.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    hr.settings = SimpleNamespace(IBKR_PORT=port)
    _reset_cache()
    alive, p = hr._check_ibgateway_alive()
    assert alive is False
    assert p == port


def test_cache_serves_within_ttl():
    # Prime the cache as alive on a closed port; a call within TTL must return the
    # cached True without re-probing (which would otherwise report False).
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    hr.settings = SimpleNamespace(IBKR_PORT=port)
    hr._ibgw_health_cache.update(checked_at=time.monotonic(), alive=True, port=port)
    alive, p = hr._check_ibgateway_alive()
    assert alive is True
    assert p == port


def test_port_fallback_when_setting_missing():
    hr.settings = SimpleNamespace()  # no IBKR_PORT attr → default 4002
    _reset_cache()
    _alive, p = hr._check_ibgateway_alive()
    assert p == 4002


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
