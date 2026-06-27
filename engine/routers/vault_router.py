"""
Vault router — Obsidian second-brain status + on-demand jobs.
====================================================================
Read and trigger the overnight vault automations (synthesis brief, thesis
contradiction check, wikilink lint) from the API instead of only PM2 cron.

This router is INFORMATIONAL / KNOWLEDGE-BASE ONLY. It never reads or writes
LIVE_TRADING_ENABLED, safety_layer.py, engine/.env, or the order path. The
vault modules read notes, call Claude, and write markdown back into the vault.

Endpoints:
  GET  /vault/status                  vault root, folder counts, latest reports, flags
  GET  /vault/brief/latest            most recent synthesis brief (404 if none)
  GET  /vault/contradictions/latest   most recent contradiction report (404 if none)
  GET  /vault/lint/latest             most recent lint report (404 if none)
  POST /vault/brief/run               run synthesis brief now (409 unless armed)
  POST /vault/contradictions/run      run contradiction check now (409 unless armed)
  POST /vault/lint/run                run wikilink lint now (409 unless armed)

The POST handlers honour the SAME ENABLE_VAULT_* flags the cron scripts read,
so the API cannot bypass a gate that is intentionally off.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from middleware.auth import verify_api_key
from vault import lint, paths

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vault", tags=["vault"], dependencies=[Depends(verify_api_key)])

# Report kind → (00-Inbox filename prefix, env flag that arms its job).
_REPORTS: dict[str, tuple[str, str]] = {
    "brief": ("brief-", "ENABLE_VAULT_SYNTHESIS"),
    "contradictions": ("contradictions-", "ENABLE_VAULT_CONTRADICTION"),
    "lint": ("lint-", "ENABLE_VAULT_LINT"),
}


# ── Response models ───────────────────────────────────────────────────────────


class VaultStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vault_root: str
    folder_note_counts: dict[str, int]
    latest_reports: dict[str, str | None]
    flags: dict[str, bool]


class JobResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: str
    written: bool
    path: str | None
    detail: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _latest_report(prefix: str) -> Path | None:
    """Most recent 00-Inbox note whose filename starts with ``prefix``."""
    inbox = paths.vault_root() / paths.INBOX
    if not inbox.exists():
        return None
    matches = [p for p in inbox.glob(f"{prefix}*.md") if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _make_llm_client():
    """Build the LLM client for the synthesis jobs.

    Factored out (and the heavy import deferred) so the router stays light to
    import and tests can monkeypatch it with a fake — no network in CI.
    """
    from llm.client import JarvisLLMClient

    return JarvisLLMClient(api_key=os.getenv("ANTHROPIC_API_KEY", "") or "ollama-local")


# ── Status ────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=VaultStatus, summary="Vault status snapshot")
async def get_vault_status() -> VaultStatus:
    try:
        root = paths.vault_root()
        counts: dict[str, int] = {}
        for folder in paths.VAULT_FOLDERS:
            base = root / folder
            counts[folder] = (
                sum(1 for p in base.rglob("*.md") if p.is_file()) if base.exists() else 0
            )
        latest: dict[str, str | None] = {}
        for kind, (prefix, _flag_name) in _REPORTS.items():
            report = _latest_report(prefix)
            latest[kind] = report.name if report is not None else None
        flags = {
            "ENABLE_VAULT_SYNTHESIS": _flag("ENABLE_VAULT_SYNTHESIS"),
            "ENABLE_VAULT_CONTRADICTION": _flag("ENABLE_VAULT_CONTRADICTION"),
            "ENABLE_VAULT_LINT": _flag("ENABLE_VAULT_LINT"),
            "ENABLE_VAULT_BACKUP": _flag("ENABLE_VAULT_BACKUP"),
        }
        return VaultStatus(
            vault_root=str(root),
            folder_note_counts=counts,
            latest_reports=latest,
            flags=flags,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("vault status failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"vault status failed: {exc}") from exc


# ── Latest report reads ───────────────────────────────────────────────────────


def _read_latest_or_404(kind: str) -> str:
    prefix = _REPORTS[kind][0]
    report = _latest_report(prefix)
    if report is None:
        raise HTTPException(status_code=404, detail=f"no {kind} report found in 00-Inbox")
    try:
        return report.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not read {kind} report: {exc}") from exc


@router.get("/brief/latest", response_class=PlainTextResponse, summary="Latest synthesis brief")
async def get_latest_brief() -> str:
    return _read_latest_or_404("brief")


@router.get(
    "/contradictions/latest",
    response_class=PlainTextResponse,
    summary="Latest contradiction report",
)
async def get_latest_contradictions() -> str:
    return _read_latest_or_404("contradictions")


@router.get("/lint/latest", response_class=PlainTextResponse, summary="Latest lint report")
async def get_latest_lint() -> str:
    return _read_latest_or_404("lint")


# ── On-demand runs ────────────────────────────────────────────────────────────


def _require_armed(kind: str) -> None:
    flag_name = _REPORTS[kind][1]
    if not _flag(flag_name):
        raise HTTPException(
            status_code=409,
            detail=f"{kind} job disabled — set {flag_name}=1 in engine/.env to arm it",
        )


async def _run_synthesis(kind: str, runner_name: str) -> JobResult:
    from vault import synthesis

    _require_armed(kind)
    runner = getattr(synthesis, runner_name)
    if kind == "brief":
        days = int(os.getenv("VAULT_SYNTHESIS_DAYS", "7"))
        model = os.getenv("VAULT_SYNTHESIS_MODEL", synthesis.DEFAULT_SYNTHESIS_MODEL)
    else:
        days = int(os.getenv("VAULT_CONTRADICTION_DAYS", "30"))
        model = os.getenv("VAULT_CONTRADICTION_MODEL", synthesis.DEFAULT_SYNTHESIS_MODEL)

    client = _make_llm_client()
    try:
        out = await runner(client, days=days, model=model)
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            await close()

    if out is None:
        return JobResult(
            job=kind, written=False, path=None, detail="no report produced (no notes or LLM down)"
        )
    return JobResult(job=kind, written=True, path=str(out), detail="report written")


@router.post("/brief/run", response_model=JobResult, summary="Run synthesis brief now")
async def run_brief() -> JobResult:
    try:
        return await _run_synthesis("brief", "run_synthesis_brief")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("vault brief run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"brief run failed: {exc}") from exc


@router.post(
    "/contradictions/run", response_model=JobResult, summary="Run contradiction check now"
)
async def run_contradictions() -> JobResult:
    try:
        return await _run_synthesis("contradictions", "run_contradiction_check")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("vault contradiction run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"contradiction run failed: {exc}") from exc


@router.post("/lint/run", response_model=JobResult, summary="Run wikilink lint now")
async def run_lint() -> JobResult:
    try:
        _require_armed("lint")
        out = lint.run_lint()
        if out is None:
            return JobResult(
                job="lint", written=False, path=None, detail="no notes in vault to scan"
            )
        return JobResult(job="lint", written=True, path=str(out), detail="report written")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("vault lint run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"lint run failed: {exc}") from exc
