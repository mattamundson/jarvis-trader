"""Minimal iii-compatible REST server for jarvis-trader RL experiments.

Serves on port 3111 when run directly. State persists to experiment_log.json
in the same directory. Compatible with n-autoresearch's run_full_cycle.py.

DO NOT IMPORT/RUN IN PRODUCTION — plumbing only.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).parent / "experiment_log.json"
SEARCH_SPACE_PATH = Path(__file__).parent / "rl_search_space.json"


def _load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"experiments": [], "search_state": "explore", "next_id": 1}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


app = FastAPI(title="jarvis-trader iii-compat sidecar")


class SetupRequest(BaseModel):
    name: str = ""
    tags: List[str] = []


class RegisterRequest(BaseModel):
    experiment_id: int
    hyperparams: Dict[str, Any]
    hypothesis: str = ""
    parent_id: int | None = None


class CompleteRequest(BaseModel):
    experiment_id: int
    val_bpb: float
    metrics: Dict[str, Any] = {}


class CrashRequest(BaseModel):
    experiment_id: int
    reason: str


@app.post("/api/experiment/setup")
def setup(req: SetupRequest):
    state = _load_state()
    eid = state["next_id"]
    state["next_id"] += 1
    state["experiments"].append({
        "id": eid,
        "name": req.name,
        "tags": req.tags,
        "status": "setup",
        "created_at": time.time(),
    })
    _save_state(state)
    return {"experiment_id": eid}


@app.post("/api/experiment/register")
def register(req: RegisterRequest):
    state = _load_state()
    for exp in state["experiments"]:
        if exp["id"] == req.experiment_id:
            exp.update({
                "hyperparams": req.hyperparams,
                "hypothesis": req.hypothesis,
                "parent_id": req.parent_id,
                "status": "registered",
            })
            _save_state(state)
            return {"ok": True}
    raise HTTPException(404, f"experiment {req.experiment_id} not found")


@app.post("/api/experiment/complete")
def complete(req: CompleteRequest):
    state = _load_state()
    for exp in state["experiments"]:
        if exp["id"] == req.experiment_id:
            exp.update({
                "val_bpb": req.val_bpb,
                "metrics": req.metrics,
                "status": "completed",
                "completed_at": time.time(),
            })
            _save_state(state)
            return {"ok": True}
    raise HTTPException(404, f"experiment {req.experiment_id} not found")


@app.post("/api/experiment/crash")
def crash(req: CrashRequest):
    state = _load_state()
    for exp in state["experiments"]:
        if exp["id"] == req.experiment_id:
            exp.update({"status": "crashed", "crash_reason": req.reason})
            _save_state(state)
            return {"ok": True}
    raise HTTPException(404, f"experiment {req.experiment_id} not found")


@app.get("/api/search/suggest")
def suggest():
    """Return a naive round-robin suggestion from rl_search_space.json."""
    if not SEARCH_SPACE_PATH.exists():
        return {"hyperparams": {}, "note": "no search space defined"}
    try:
        space = json.loads(SEARCH_SPACE_PATH.read_text())
        params = space.get("params", [])
        if not params:
            return {"hyperparams": {}}
        suggestion = {}
        for p in params:
            if p.get("type") == "float":
                lo, hi = p["bounds"]
                suggestion[p["name"]] = (lo + hi) / 2
            elif p.get("type") == "int":
                lo, hi = p["bounds"]
                suggestion[p["name"]] = int((lo + hi) / 2)
            elif p.get("type") == "categorical":
                suggestion[p["name"]] = p["options"][0]
        return {"hyperparams": suggestion, "strategy": "midpoint_baseline"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/search/adapt")
def adapt(state_update: Dict[str, Any]):
    state = _load_state()
    state["search_state"] = state_update.get("strategy", state["search_state"])
    _save_state(state)
    return {"ok": True, "current_state": state["search_state"]}


@app.get("/api/search/strategy")
def strategy():
    state = _load_state()
    return {
        "strategy": state.get("search_state", "explore"),
        "experiment_count": len(state.get("experiments", [])),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3111)
