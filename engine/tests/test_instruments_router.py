"""
Tests for engine/routers/instruments_router.py

Covered:
  - GET  /instruments/wfe-status              — success with default seed data;
                                                  falls back to defaults when the
                                                  cache file is corrupt JSON
  - POST /instruments/wfe-status/{symbol}     — success (persists + returns
                                                  updated status, status derived
                                                  from WFE thresholds); 422 on
                                                  bad input (wrong field type)
  - auth-missing returns 401

Design:
  - Uses a minimal FastAPI app wrapping only instruments_router (no full
    main.py import), mirroring tests/test_admin_router.py.
  - APIKeyMiddleware is added manually so auth tests are realistic.
  - The router's only external dependency is the on-disk WFE_CACHE_PATH json
    file. Every test monkeypatches routers.instruments_router.WFE_CACHE_PATH
    to a pytest tmp_path so the real engine/data/wfe_cache.json is never
    read or written.
  - Never touches engine/.env or any live endpoint.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


_load_env()

from config import settings  # noqa: E402 — must follow _load_env()
from middleware.api_key_middleware import APIKeyMiddleware  # noqa: E402
from routers import instruments_router  # noqa: E402
from routers.instruments_router import router as instruments_api_router  # noqa: E402

_VALID_HEADERS = {"X-API-Key": settings.API_KEY}
_BAD_HEADERS = {"X-API-Key": "wrong-key"}


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.add_middleware(APIKeyMiddleware)
    _app.include_router(instruments_api_router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _isolate_wfe_cache(tmp_path, monkeypatch):
    """Redirect WFE_CACHE_PATH so tests never touch the real data file."""
    fake_path = tmp_path / "wfe_cache.json"
    monkeypatch.setattr(instruments_router, "WFE_CACHE_PATH", fake_path)
    yield fake_path


# ---------------------------------------------------------------------------
# GET /instruments/wfe-status
# ---------------------------------------------------------------------------


def test_wfe_status_success_uses_defaults_when_no_cache_file(client: TestClient) -> None:
    resp = client.get("/instruments/wfe-status", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["summary"]["total_instruments"] == len(instruments_router.DEFAULT_WFE_DATA)
    symbols = {i["symbol"] for i in data["instruments"]}
    assert symbols == set(instruments_router.DEFAULT_WFE_DATA.keys())

    # MES seeded at wfe=0.09 (< 0.40 alert threshold) must be flagged.
    mes = next(i for i in data["instruments"] if i["symbol"] == "MES")
    assert mes["alert"] is True
    assert "below minimum threshold" in mes["alert_reason"]

    # MCL seeded at wfe=0.82, APPROVED, should not alert on WFE (may or may not
    # alert on recalculation overdue depending on today's date, but must not
    # cite the WFE-threshold reason).
    mcl = next(i for i in data["instruments"] if i["symbol"] == "MCL")
    if mcl["alert_reason"]:
        assert "below minimum threshold" not in mcl["alert_reason"]


def test_wfe_status_reads_persisted_cache_file(client: TestClient, _isolate_wfe_cache) -> None:
    today_str = date.today().isoformat()
    cache_data = {
        "MES": {
            "wfe": 0.91,
            "interval": "1h",
            "status": "APPROVED",
            "last_calculated": today_str,
        }
    }
    _isolate_wfe_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_wfe_cache.write_text(json.dumps(cache_data))

    resp = client.get("/instruments/wfe-status", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    mes = next(i for i in data["instruments"] if i["symbol"] == "MES")
    assert mes["wfe"] == 0.91
    assert mes["alert"] is False  # fresh + above threshold


def test_wfe_status_corrupt_cache_file_falls_back_to_defaults(
    client: TestClient, _isolate_wfe_cache
) -> None:
    """Mocked-dependency-failure path: on-disk cache is corrupt JSON."""
    _isolate_wfe_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_wfe_cache.write_text("{not valid json::")

    resp = client.get("/instruments/wfe-status", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    symbols = {i["symbol"] for i in data["instruments"]}
    assert symbols == set(instruments_router.DEFAULT_WFE_DATA.keys())


def test_wfe_status_auth_required(client: TestClient) -> None:
    resp = client.get("/instruments/wfe-status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /instruments/wfe-status/{symbol}
# ---------------------------------------------------------------------------


def test_update_wfe_status_success_approved(
    client: TestClient, _isolate_wfe_cache
) -> None:
    resp = client.post(
        "/instruments/wfe-status/mgc",
        json={"wfe": 0.75, "interval": "1d"},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["symbol"] == "MGC"  # uppercased
    assert data["instrument"]["wfe"] == 0.75
    assert data["instrument"]["status"] == "APPROVED"

    # Persisted to disk at the redirected path.
    persisted = json.loads(_isolate_wfe_cache.read_text())
    assert persisted["MGC"]["wfe"] == 0.75


def test_update_wfe_status_low_score_sets_do_not_trade(
    client: TestClient, _isolate_wfe_cache
) -> None:
    resp = client.post(
        "/instruments/wfe-status/MES",
        json={"wfe": 0.05, "interval": "1h"},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["instrument"]["status"] == "DO_NOT_TRADE"


def test_update_wfe_status_marginal_score_keeps_existing_status(
    client: TestClient, _isolate_wfe_cache
) -> None:
    """WFE in [0.40, 0.50) keeps the instrument's current status rather than
    forcing APPROVED — seed MGC as HALTED first, then submit a marginal score."""
    _isolate_wfe_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolate_wfe_cache.write_text(
        json.dumps(
            {
                "MGC": {
                    "wfe": 0.14,
                    "interval": "1d",
                    "status": "HALTED",
                    "last_calculated": "2026-03-30",
                }
            }
        )
    )

    resp = client.post(
        "/instruments/wfe-status/MGC",
        json={"wfe": 0.45, "interval": "1d"},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["instrument"]["status"] == "HALTED"


def test_update_wfe_status_bad_input_wrong_type_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/instruments/wfe-status/MES",
        json={"wfe": "not-a-number", "interval": "1h"},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 422, resp.text


def test_update_wfe_status_missing_field_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/instruments/wfe-status/MES",
        json={"wfe": 0.6},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 422, resp.text


def test_update_wfe_status_auth_required(client: TestClient) -> None:
    resp = client.post("/instruments/wfe-status/MES", json={"wfe": 0.6, "interval": "1h"})
    assert resp.status_code == 401
