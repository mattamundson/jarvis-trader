#!/usr/bin/env python3
"""Register an n-autoresearch experiment with robust JSON handling."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def git_short_sha(repo_dir: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_dir,
        text=True,
    ).strip()


def unwrap_body(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("body"), dict):
        return result["body"]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--category", required=True)
    ap.add_argument("--description", required=True)
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--diff-summary", required=True)
    ap.add_argument("--parent-id", default=None)
    ap.add_argument("--commit-sha", default=None)
    ap.add_argument("--gpu-id", default=None)
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--base-url", default="http://localhost:3111")
    ap.add_argument("--print-id-only", action="store_true")
    args = ap.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    commit_sha = args.commit_sha or git_short_sha(repo_dir)

    payload = {
        "tag": args.tag,
        "hypothesis": args.hypothesis,
        "description": args.description,
        "category": args.category,
        "commit_sha": commit_sha,
        "diff_summary": args.diff_summary,
        "parent_id": args.parent_id,
    }
    if args.gpu_id:
        payload["gpu_id"] = args.gpu_id

    try:
        result = post(args.base_url, "/api/experiment/register", payload)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 2

    body = unwrap_body(result)
    if args.print_id_only:
        print(body.get("experiment_id", ""))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
