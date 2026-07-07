#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: parse_run_log.py <run.log>", file=sys.stderr)
        return 1
    path = Path(sys.argv[1])
    text = path.read_text(errors="replace")
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

    normalized = {
        "val_bpb": out.get("val_bpb"),
        "peak_vram_mb": out.get("peak_vram_mb", 0.0),
        "training_seconds": out.get("training_seconds", 0.0),
        "total_tokens_m": out.get("total_tokens_M", 0.0),
        "mfu_percent": out.get("mfu_percent", 0.0),
        "num_steps": out.get("num_steps", 0),
        "num_params_m": out.get("num_params_M", 0.0),
        "depth": out.get("depth", 0),
    }
    print(json.dumps(normalized, indent=2))
    return 0 if normalized["val_bpb"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
