#!/usr/bin/env python3
"""Bias may change only on a 15-minute close beyond a pre-named level.

Usage:
  bias_gate.py --state state.json --propose bullish --asof '2026-11-05 22:05'
  bias_gate.py --demo

State schema:
  {
    "bias": "neutral",
    "named_levels": {"break_up": 7392, "break_down": 7383},
    "updated_ct": "..."
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from lib.prices import load_es_5m, last_closed_15m_close  # noqa: E402
from lib.timeutil import CT, parse_ct, to_ct_str  # noqa: E402


DEFAULT_STATE = ROOT / "data" / "bias_state.json"


def evaluate(state: dict, proposed_bias: str, asof: datetime, bars_5m=None) -> dict:
    """Return allowed bias + reason. Never mutates unless caller writes."""
    prior = state.get("bias") or "neutral"
    levels = state.get("named_levels") or {}
    break_up = levels.get("break_up")
    break_down = levels.get("break_down")
    if proposed_bias == prior:
        return {
            "allowed_bias": prior,
            "changed": False,
            "reason": "proposed equals prior",
            "asof_ct": to_ct_str(asof),
            "15m_close": None,
        }
    bars_5m = bars_5m if bars_5m is not None else load_es_5m(prefer="auto")
    closed = last_closed_15m_close(bars_5m, asof)
    if closed is None:
        return {
            "allowed_bias": prior,
            "changed": False,
            "reason": "no closed 15m bar yet — keep prior bias",
            "asof_ct": to_ct_str(asof),
            "15m_close": None,
        }
    close_ts, close_px = closed
    # Changing to bullish requires 15m close >= break_up
    if proposed_bias == "bullish":
        if break_up is None:
            return {
                "allowed_bias": prior,
                "changed": False,
                "reason": "no pre-named break_up level — cannot flip bullish",
                "asof_ct": to_ct_str(asof),
                "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
            }
        if close_px >= float(break_up):
            return {
                "allowed_bias": "bullish",
                "changed": True,
                "reason": f"15m close {close_px} >= break_up {break_up}",
                "asof_ct": to_ct_str(asof),
                "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
            }
        return {
            "allowed_bias": prior,
            "changed": False,
            "reason": f"15m close {close_px} < break_up {break_up} — keep prior",
            "asof_ct": to_ct_str(asof),
            "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
        }
    if proposed_bias == "bearish":
        if break_down is None:
            return {
                "allowed_bias": prior,
                "changed": False,
                "reason": "no pre-named break_down level — cannot flip bearish",
                "asof_ct": to_ct_str(asof),
                "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
            }
        if close_px <= float(break_down):
            return {
                "allowed_bias": "bearish",
                "changed": True,
                "reason": f"15m close {close_px} <= break_down {break_down}",
                "asof_ct": to_ct_str(asof),
                "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
            }
        return {
            "allowed_bias": prior,
            "changed": False,
            "reason": f"15m close {close_px} > break_down {break_down} — keep prior",
            "asof_ct": to_ct_str(asof),
            "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
        }
    # neutral/watch always allowed (de-risk)
    if proposed_bias in ("neutral", "watch"):
        return {
            "allowed_bias": proposed_bias,
            "changed": proposed_bias != prior,
            "reason": "neutral/watch always allowed (de-risk)",
            "asof_ct": to_ct_str(asof),
            "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
        }
    return {
        "allowed_bias": prior,
        "changed": False,
        "reason": f"unknown proposed bias {proposed_bias!r}",
        "asof_ct": to_ct_str(asof),
        "15m_close": {"ts_ct": to_ct_str(close_ts), "close": close_px},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--propose", required=False)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--write", action="store_true", help="persist allowed bias to state file")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    if args.demo:
        state = {"bias": "neutral", "named_levels": {"break_up": 7392.0, "break_down": 7383.0},
                 "updated_ct": "2026-11-05 21:52"}
        # recreate 10:05 bearish flip attempt
        asof = parse_ct("2026-11-05 22:05")
        r = evaluate(state, "bearish", asof)
        print(json.dumps({"scenario": "10:05 bearish flip attempt", "result": r}, indent=2))
        return
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "bias": "neutral", "named_levels": {}, "updated_ct": None
    }
    asof = parse_ct(args.asof) if args.asof else datetime.now(CT)
    proposed = args.propose or state.get("bias") or "neutral"
    result = evaluate(state, proposed, asof)
    if args.write and result["changed"]:
        state["bias"] = result["allowed_bias"]
        state["updated_ct"] = result["asof_ct"]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        result["wrote"] = str(state_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
