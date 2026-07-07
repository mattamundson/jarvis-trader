"""P1.0: the Prometheus exposition endpoint must be mounted and auth-exempt.

The jarvis_* metric families are defined in monitoring/metrics.py but nothing
mounted a /metrics endpoint (it 404s on the live engine) and /metrics was not in
the auth allowlist — so Prometheus had nothing to scrape and would have rendered
empty Grafana panels. These tests pin the real wiring:

- mount_metrics(app) serves the jarvis_* families at /metrics, and
- /metrics is in EXEMPT_PATHS so Prometheus can scrape it without the API key.

Tested on a bare FastAPI app (not main.py) so the heavy engine lifespan / IB
connections never boot — the production wiring is the single mount_metrics()
call, exercised here directly.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_metrics_scrapeable_keyless_through_auth_middleware():
    """Reproduce the LIVE condition the bare-app test missed: with the real
    APIKeyMiddleware attached, GET /metrics 307-redirects to /metrics/, which
    must ALSO be auth-exempt or Prometheus scrapes get 401. TestClient follows
    the redirect, so this asserts the end-to-end keyless scrape works."""
    from middleware.api_key_middleware import APIKeyMiddleware
    from monitoring import metrics

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    metrics.mount_metrics(app)
    client = TestClient(app)

    r = client.get("/metrics")  # no X-API-Key — Prometheus scrapes keyless
    assert r.status_code == 200
    assert "jarvis_kill_switch_active" in r.text


def test_metrics_path_is_auth_exempt():
    from middleware.auth import EXEMPT_PATHS

    assert "/metrics" in EXEMPT_PATHS


def test_mount_metrics_serves_jarvis_families_without_key():
    from monitoring import metrics

    app = FastAPI()
    metrics.mount_metrics(app)
    client = TestClient(app)

    # No X-API-Key header — Prometheus scrapes keyless.
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # Unlabeled gauge: always emits a sample line regardless of activity.
    assert "jarvis_kill_switch_active" in body
    # Labeled family: HELP/TYPE lines are emitted even before any sample.
    assert "jarvis_pipeline_runs_total" in body
    assert "jarvis_equity_usd" in body


def test_mount_metrics_reflects_recorded_values():
    from monitoring import metrics

    metrics.set_kill_switch(True)
    metrics.set_consecutive_losses(11)

    app = FastAPI()
    metrics.mount_metrics(app)
    client = TestClient(app)
    body = client.get("/metrics").text

    assert "jarvis_kill_switch_active 1.0" in body
    assert "jarvis_consecutive_losses 11.0" in body


def test_sync_safety_gauges_sets_all_four_from_snapshot():
    from prometheus_client import REGISTRY

    from monitoring import metrics

    metrics.sync_safety_gauges(
        {
            "kill_switch_active": True,
            "daily_pnl": -123.45,
            "portfolio_equity": 8525.41,
            "consecutive_losses": 11,
        }
    )
    assert REGISTRY.get_sample_value("jarvis_kill_switch_active") == 1.0
    assert REGISTRY.get_sample_value("jarvis_daily_pnl_usd") == -123.45
    assert REGISTRY.get_sample_value("jarvis_equity_usd") == 8525.41
    assert REGISTRY.get_sample_value("jarvis_consecutive_losses") == 11.0


def test_sync_safety_gauges_tolerates_partial_snapshot_and_never_raises():
    from prometheus_client import REGISTRY

    from monitoring import metrics

    # Seed a known value, then sync a snapshot missing that key — it must be left
    # untouched (not reset to 0) and the call must not raise.
    metrics.set_equity(9999.0)
    metrics.sync_safety_gauges({"kill_switch_active": False})
    assert REGISTRY.get_sample_value("jarvis_kill_switch_active") == 0.0
    assert REGISTRY.get_sample_value("jarvis_equity_usd") == 9999.0
