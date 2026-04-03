#!/usr/bin/env python3
"""Finalize an experiment by parsing a log and posting either /complete or /crash."""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:3111"
KEYS = {
    "val_bpb": float,
    "peak_vram_mb": float,
    "training_seconds": float,
    "total_tokens_M": float,
    "mfu_percent": float,
    "num_steps": int,
    "num_params_M": float,
    "depth": int,
}


def parse_metrics(text: str) -> dict:
    out = {}
    for key, caster in KEYS.items():
        m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, flags=re.MULTILINE)
        if not m:
            continue
        raw = m.group(1).strip()
        try:
            out[key] = caster(float(raw) if caster is int else raw)
        except Exception:
            try:
                out[key] = caster(raw)
            except Exception:
                out[key] = raw
    return {
        "val_bpb": out.get("val_bpb"),
        "peak_vram_mb": out.get("peak_vram_mb", 0.0),
        "training_seconds": out.get("training_seconds", 0.0),
        "total_tokens_m": out.get("total_tokens_M", 0.0),
        "mfu_percent": out.get("mfu_percent", 0.0),
        "num_steps": out.get("num_steps", 0),
        "num_params_m": out.get("num_params_M", 0.0),
        "depth": out.get("depth", 0),
    }


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: finalize_experiment.py <experiment_id> <log_path>", file=sys.stderr)
        return 1
    experiment_id = sys.argv[1]
    log_path = Path(sys.argv[2])
    text = log_path.read_text(errors="replace")
    metrics = parse_metrics(text)

    try:
        if metrics["val_bpb"] is not None:
            payload = {"experiment_id": experiment_id, **metrics}
            result = post("/api/experiment/complete", payload)
        else:
            tail = "\n".join(text.splitlines()[-50:]).strip() or "No metrics found in log"
            result = post("/api/experiment/crash", {"experiment_id": experiment_id, "error": tail[:4000]})
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
