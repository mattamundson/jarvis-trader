"""
Tests for the independent position watchdog.

The watchdog is the safety lane that runs OUTSIDE the engine process, so its
failure modes matter more than most code: a watchdog that reports "all clear"
when the engine is dead is worse than no watchdog at all.

These tests pin the behaviours that were verified live:
  1. silent + exit 0 when every check passes (cron-friendly)
  2. exit 1 + named ALERT when the engine is unreachable
  3. exit 1 + named ALERT when the gateway port is closed
  4. drawdown % computed from the REAL /portfolio/paper/performance shape
     (nested under `performance`, `avg_loss` negative, `max_dd` in DOLLARS)
  5. never raises, never prints the API key

Network calls are stubbed by monkeypatching the module's `_engine_get`, so no
test touches a live engine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the watchdog module directly from the repo script path. It is a script
# (not a package module), so importlib is used rather than a normal import.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "independent_position_watchdog.py"
_spec = importlib.util.spec_from_file_location("independent_position_watchdog", _SCRIPT)
assert _spec and _spec.loader
wd = importlib.util.module_from_spec(_spec)
sys.modules["independent_position_watchdog"] = wd
_spec.loader.exec_module(wd)


# ── helpers ──────────────────────────────────────────────────────────────────


def _stub_engine_get(responses: dict[str, tuple[dict | None, str | None]]):
    """Return a fake _engine_get driven by a path->(json, error) map."""

    def fake(path: str):
        return responses.get(path, (None, "unmapped path"))

    return fake


HEALTHY_HEALTH = {
    "status": "ok",
    "kill_switch_active": False,
    "live_trading": False,
    "ibgateway_alive": True,
}

# The REAL route shape — this is what the live engine returns.
REAL_PERFORMANCE = {
    "performance": {
        "total_pnl": 4426.5661,
        "win_rate": 0.3111,
        "profit_factor": 1.7015,
        "num_trades": 90,
        "avg_win": 383.4464,
        "avg_loss": -101.7731,   # NEGATIVE
        "max_dd": -1981.7035,    # DOLLARS, not percent
        "unrealized_pnl": 0.0,
        "open_positions": [],
    }
}


@pytest.fixture
def healthy(monkeypatch):
    """All checks pass; gateway port stubbed open."""
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get(
            {
                "/health": (HEALTHY_HEALTH, None),
                "/orders/status": ({"positions": []}, None),
                "/brokers/positions": ({"positions": []}, None),
                "/portfolio/paper/performance": (REAL_PERFORMANCE, None),
            }
        ),
    )
    monkeypatch.setattr(wd, "check_gateway", lambda report, health: report.add(
        "ibgateway_alive", wd.OK, "stubbed open"
    ))


# ── exit-code contract (cron depends on this) ────────────────────────────────


def test_silent_and_zero_when_all_checks_pass(healthy, capsys):
    rc = wd.main()
    out = capsys.readouterr().out
    assert rc == 0, "a clean tick must exit 0"
    assert out.strip() == "", "a clean tick must print NOTHING (cron silence)"


def test_alerts_and_nonzero_when_engine_unreachable(monkeypatch, capsys):
    monkeypatch.setattr(
        wd, "_engine_get", _stub_engine_get({})  # everything unmapped -> error
    )
    monkeypatch.setattr(wd, "check_gateway", lambda report, health: report.add(
        "ibgateway_alive", wd.OK, "stubbed open"
    ))

    rc = wd.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "POSITION WATCHDOG ALERT" in out
    assert "engine_alive" in out


def test_alerts_when_gateway_port_closed(monkeypatch, capsys):
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get({"/health": (HEALTHY_HEALTH, None)}),
    )
    # Real gateway probe against a certainly-dead port.
    monkeypatch.setattr(wd, "IB_PORT", 9)

    rc = wd.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "ibgateway_alive" in out


def test_alerts_on_position_disagreement(monkeypatch, capsys):
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get(
            {
                "/health": (HEALTHY_HEALTH, None),
                "/orders/status": ({"positions": [{"symbol": "MES"}]}, None),
                "/brokers/positions": ({"positions": []}, None),  # broker disagrees
                "/portfolio/paper/performance": (REAL_PERFORMANCE, None),
            }
        ),
    )
    monkeypatch.setattr(wd, "check_gateway", lambda report, health: report.add(
        "ibgateway_alive", wd.OK, "stubbed open"
    ))

    rc = wd.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "DISAGREEMENT" in out


# ── drawdown maths against the real payload shape ────────────────────────────


def test_drawdown_pct_uses_real_route_shape(healthy):
    """max_dd is DOLLARS; the % must be derived, not read."""
    report = wd.WatchdogReport()
    wd.check_drawdown(report)

    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    # peak = (10000 + 4426.57) + 1981.70 = 16408.27 ; 1981.70/16408.27 = 12.08%
    assert "12.08%" in check.detail, check.detail


def test_drawdown_alerts_above_threshold(healthy, monkeypatch):
    monkeypatch.setattr(wd, "DRAWDOWN_WARN_PCT", 5.0)
    report = wd.WatchdogReport()
    wd.check_drawdown(report)

    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    assert check.status == wd.ALERT


def test_drawdown_ok_below_threshold(healthy, monkeypatch):
    monkeypatch.setattr(wd, "DRAWDOWN_WARN_PCT", 15.0)
    report = wd.WatchdogReport()
    wd.check_drawdown(report)

    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    assert check.status == wd.OK


def test_drawdown_handles_flat_top_level_shape(monkeypatch):
    """Older/flat payloads (no `performance` wrapper) must still work."""
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get(
            {
                "/portfolio/paper/performance": (
                    {"total_pnl": 0.0, "avg_loss": -50.0, "max_dd": -500.0},
                    None,
                )
            }
        ),
    )
    report = wd.WatchdogReport()
    wd.check_drawdown(report)
    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    # peak = 10000 + 500 = 10500 ; 500/10500 = 4.76%
    assert "4.76%" in check.detail, check.detail


def test_drawdown_survives_missing_fields(monkeypatch):
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get({"/portfolio/paper/performance": ({"performance": {}}, None)}),
    )
    report = wd.WatchdogReport()
    wd.check_drawdown(report)  # must not raise
    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    assert check.status == wd.OK


def test_drawdown_survives_unparseable_values(monkeypatch):
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get(
            {
                "/portfolio/paper/performance": (
                    {"performance": {"max_dd": "nonsense", "total_pnl": "also bad"}},
                    None,
                )
            }
        ),
    )
    report = wd.WatchdogReport()
    wd.check_drawdown(report)  # must not raise
    check = next(c for c in report.checks if c.name == "drawdown_proximity")
    assert check.status == wd.OK


# ── safety properties ────────────────────────────────────────────────────────


def test_kill_switch_active_is_an_alert(monkeypatch):
    monkeypatch.setattr(
        wd,
        "_engine_get",
        _stub_engine_get(
            {
                "/health": {"kill_switch_active": True, "live_trading": False},
            }
        ),
    )
    report = wd.WatchdogReport()
    wd.check_kill_switch(report, {"kill_switch_active": True, "live_trading": False})
    check = next(c for c in report.checks if c.name == "kill_switch")
    assert check.status == wd.ALERT


def test_api_key_is_never_printed(monkeypatch, capsys):
    """A watchdog that leaks the engine key into cron output is a disclosure bug."""
    secret = "super-secret-key-value"
    monkeypatch.setenv("API_KEY", secret)
    monkeypatch.setattr(
        wd, "_engine_get", _stub_engine_get({})  # force failure path with output
    )
    monkeypatch.setattr(wd, "check_gateway", lambda report, health: None)

    wd.main()
    out = capsys.readouterr().out
    assert secret not in out


def test_engine_get_never_raises_on_bad_json(monkeypatch):
    """A malformed body must degrade to an error string, not an exception."""

    class _Resp:
        def read(self):
            return b"<html>not json</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(wd.urllib.request, "urlopen", lambda *a, **k: _Resp())
    data, err = wd._engine_get("/health")
    assert data is None
    assert err and "bad json" in err
