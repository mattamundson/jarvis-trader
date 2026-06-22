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
