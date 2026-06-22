"""Default-CI cover for the IB e2e fast pre-flight (``_port_reachable``).

The end-to-end tests in ``test_ibkr_e2e_paper.py`` are ``@pytest.mark.manual``
and deselected by ``-m "not manual"`` precisely because a firewall-dropped IB
paper port hangs the asyncio loop. These tests are NOT marked manual, so the
pre-flight guard that prevents that hang is exercised on every normal run -- no
live IB Gateway required.
"""

from __future__ import annotations

import socket
import time

from tests.test_ibkr_e2e_paper import _PREFLIGHT_TIMEOUT, _port_reachable


def test_port_reachable_true_for_open_listener():
    """A real listening socket is reported reachable."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert _port_reachable("127.0.0.1", port) is True
    finally:
        srv.close()


def test_port_reachable_false_and_fast_for_closed_port():
    """Nothing listening -> False, and it must return fast (never hang)."""
    # Reserve then release a port so we know nothing is listening on it.
    tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()

    start = time.monotonic()
    result = _port_reachable("127.0.0.1", port, timeout=_PREFLIGHT_TIMEOUT)
    elapsed = time.monotonic() - start

    assert result is False
    # The whole point: a closed/dropped port resolves within the bounded
    # timeout instead of stalling the suite.
    assert elapsed < _PREFLIGHT_TIMEOUT + 1.0


def test_port_reachable_accepts_custom_timeout():
    """The timeout parameter is honoured without raising."""
    assert _port_reachable("127.0.0.1", 0, timeout=0.2) is False
