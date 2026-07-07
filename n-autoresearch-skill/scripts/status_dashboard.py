#!/usr/bin/env python3
"""Small CLI dashboard for n-autoresearch status."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any, Dict

BASE = "http://localhost:3111"


def get(path: str) -> Dict[str, Any]:
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def render(tag: str | None) -> str:
    pool = get("/api/pool/list")
    tags = get("/api/report/tags")
    lines = []
    lines.append("=" * 72)
    lines.append("n-autoresearch status")
    lines.append("=" * 72)
    lines.append(f"GPU pool: total={pool.get('total', 0)} idle={pool.get('idle', 0)} training={pool.get('training', 0)} offline={pool.get('offline', 0)}")

    tag_items = tags.get("body", {}).get("tags", []) if "body" in tags else tags.get("tags", [])
    if not tag_items:
        lines.append("No tags found.")
        return "\n".join(lines)

    if tag is None:
        tag = tag_items[0]["name"]

    summary = post("/api/report/summary", {"tag": tag})
    summary_body = summary.get("body", summary)
    lines.append(f"Active tag: {tag}")
    best = summary_body.get("best")
    if best:
        lines.append(f"Best: {best.get('val_bpb')} (exp={best.get('experiment_id')}, commit={best.get('commit')})")
    else:
        lines.append("Best: none yet")

    stats = summary_body.get("stats", {})
    lines.append(
        "Stats: total={total} kept={kept} discarded={discarded} crashed={crashed} running={running} keep_rate={keep_rate:.2%}".format(
            total=stats.get("total", 0),
            kept=stats.get("kept", 0),
            discarded=stats.get("discarded", 0),
            crashed=stats.get("crashed", 0),
            running=stats.get("running", 0),
            keep_rate=stats.get("keep_rate", 0.0),
        )
    )
    lines.append(f"Strategy: {summary_body.get('strategy', 'unknown')}")
    cats = summary_body.get("categories", {})
    if cats:
        lines.append("Categories: " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
    progression = summary_body.get("bpb_progression", [])
    if progression:
        lines.append("Recent kept experiments:")
        for item in progression[-5:]:
            lines.append(f"  - {item.get('id')}: val_bpb={item.get('val_bpb')} | {item.get('description')} | {item.get('category')}")
    lines.append("Recent tags:")
    for item in tag_items[:5]:
        lines.append(f"  - {item.get('name')} total={item.get('total_experiments')} best={item.get('best_val_bpb')}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None)
    ap.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    args = ap.parse_args()

    if args.watch > 0:
        while True:
            print("\x1bc", end="")
            print(render(args.tag))
            time.sleep(args.watch)
    else:
        print(render(args.tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
