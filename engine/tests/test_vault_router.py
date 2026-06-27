"""Tests for the vault API router (engine/routers/vault_router.py).

A minimal FastAPI app mounts only the vault router so the suite does not import
the full engine. Auth is overridden and the LLM client is faked — no network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import verify_api_key
from routers import vault_router
from vault import paths


class FakeClient:
    """Duck-typed JarvisLLMClient stand-in."""

    async def call(self, **kwargs):
        return SimpleNamespace(success=True, content="## Connections\nfaked", error=None)

    async def close(self):
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_VAULT_ROOT", str(tmp_path))
    # Default every flag off; individual tests arm what they need.
    for flag in (
        "ENABLE_VAULT_SYNTHESIS",
        "ENABLE_VAULT_CONTRADICTION",
        "ENABLE_VAULT_LINT",
        "ENABLE_VAULT_BACKUP",
    ):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setattr(vault_router, "_make_llm_client", lambda: FakeClient())

    app = FastAPI()
    app.include_router(vault_router.router)
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    return TestClient(app)


def test_status_shape(client, tmp_path):
    paths.write_note(paths.SOURCES, "a.md", "note", root=tmp_path)
    resp = client.get("/vault/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vault_root"] == str(tmp_path)
    assert set(body["folder_note_counts"]) == set(paths.VAULT_FOLDERS)
    assert body["folder_note_counts"][paths.SOURCES] == 1
    assert set(body["latest_reports"]) == {"brief", "contradictions", "lint"}
    assert body["flags"]["ENABLE_VAULT_LINT"] is False


def test_latest_404_when_empty(client):
    assert client.get("/vault/lint/latest").status_code == 404
    assert client.get("/vault/brief/latest").status_code == 404


def test_run_returns_409_when_disabled(client):
    assert client.post("/vault/lint/run").status_code == 409
    assert client.post("/vault/brief/run").status_code == 409
    assert client.post("/vault/contradictions/run").status_code == 409


def test_lint_run_writes_when_armed(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_VAULT_LINT", "1")
    paths.write_note(paths.SOURCES, "a.md", "See [[ghost]].", root=tmp_path)
    resp = client.post("/vault/lint/run")
    assert resp.status_code == 200
    assert resp.json()["written"] is True
    # The report is now readable via the latest endpoint.
    latest = client.get("/vault/lint/latest")
    assert latest.status_code == 200
    assert "ghost" in latest.text


def test_brief_run_uses_fake_client_when_armed(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_VAULT_SYNTHESIS", "1")
    paths.write_note(paths.SOURCES, "a.md", "institutional flows compress vol", root=tmp_path)
    resp = client.post("/vault/brief/run")
    assert resp.status_code == 200
    assert resp.json()["written"] is True
    assert "faked" in client.get("/vault/brief/latest").text
