"""JARVIS DOM / Order-Flow service — Phase 1 (port 8030).

Isolated FastAPI service for MES depth-of-market + order-flow-imbalance
visualization. Read-only market-data consumer: imports nothing from
``engine.risk`` / ``engine.config`` and has no path to order placement.

Endpoints:
    GET /domflow/mes/latest              — latest computed snapshot
    GET /domflow/mes/history?minutes=N   — stored snapshots for the last N min

Run via PM2 (jarvis-domflow) with the same isolation pattern as
``jarvis-bridge-api``:
    .venv/Scripts/python.exe -m uvicorn domflow.main:app --host 127.0.0.1 --port 8030
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .ib_client import DomflowIBClient
from .storage import DomflowStorage

logger = logging.getLogger("domflow")

app = FastAPI(title="JARVIS DOM/Order-Flow", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton service state, wired in lifespan (avoids import-time side effects).
_service: dict = {"client": None, "storage": None, "loop_task": None}

SNAPSHOT_INTERVAL_S = float(os.environ.get("DOMFLOW_SNAPSHOT_INTERVAL", "10"))
PRUNE_INTERVAL_S = 3600.0
PRUNE_KEEP_DAYS = 30


async def _snapshot_loop() -> None:
    """Persist a snapshot every 10s and prune old rows hourly."""
    client: DomflowIBClient = _service["client"]
    storage: DomflowStorage = _service["storage"]
    last_prune = asyncio.get_running_loop().time()
    while True:
        try:
            snap = client.current_snapshot()
            storage.insert_snapshot(
                symbol=snap.symbol,
                ts_utc=snap.ts_utc,
                best_bid=snap.best_bid,
                best_ask=snap.best_ask,
                mid_price=snap.mid_price,
                spread=snap.spread,
                bid_volume_top5=snap.bid_volume_top5,
                ask_volume_top5=snap.ask_volume_top5,
                imbalance_ratio=snap.imbalance_ratio,
                raw_book_json=snap.raw_book_json,
            )
            now = asyncio.get_running_loop().time()
            if now - last_prune >= PRUNE_INTERVAL_S:
                removed = storage.prune(keep_days=PRUNE_KEEP_DAYS)
                if removed:
                    logger.info("domflow: pruned %d old snapshot(s)", removed)
                last_prune = now
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — the loop must never die
            logger.warning("domflow: snapshot loop error: %s", e)
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    client = DomflowIBClient()
    storage = DomflowStorage()
    storage.connect()
    _service["client"] = client
    _service["storage"] = storage

    # Non-fatal connect: if IB is down the service still serves stale last-known.
    await client.start()
    loop_task = asyncio.create_task(_snapshot_loop())
    _service["loop_task"] = loop_task
    logger.info("domflow: service started (client connected=%s)", client.connected)
    try:
        yield
    finally:
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
        await client.stop()
        storage.close()


app.router.lifespan_context = lifespan


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/domflow/mes/latest")
async def latest_snapshot():
    client: DomflowIBClient = _service.get("client")
    storage: DomflowStorage = _service.get("storage")
    if client is None:
        raise HTTPException(status_code=503, detail="domflow service not initialized")

    snap = client.current_snapshot()
    payload = snap.as_dict()

    # If the live book is empty/stale, fall back to the last persisted row so
    # the dashboard always has *something* with an honest staleness marker.
    if (payload.get("best_bid") is None and payload.get("best_ask") is None) and storage is not None:
        last = storage.latest(symbol="MES")
        if last:
            payload = {**last, "stale": True, "connected": client.connected}
            if "ts_utc" in last:
                try:
                    ts = datetime.fromisoformat(last["ts_utc"])
                    payload["age_seconds"] = max(
                        0.0, (datetime.now(timezone.utc) - ts).total_seconds()
                    )
                except ValueError:
                    pass
    return payload


@app.get("/domflow/mes/history")
async def history(minutes: int = Query(60, ge=1, le=1440)):
    storage: DomflowStorage = _service.get("storage")
    if storage is None:
        raise HTTPException(status_code=503, detail="domflow service not initialized")
    rows = storage.history(symbol="MES", minutes=minutes)
    return {"symbol": "MES", "minutes": minutes, "count": len(rows), "snapshots": rows}
