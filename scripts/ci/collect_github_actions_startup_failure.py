#!/usr/bin/env python3
"""Collect sanitized GitHub Actions startup-failure evidence.

This script shells out to `gh api` so it uses the same authenticated context as
operator CLI diagnostics. It writes JSON only and never reads repository secrets.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

DEFAULT_REPO = "mattamundson/jarvis-trader"


def _gh_api(path: str) -> tuple[int, Any]:
    proc = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return proc.returncode, {
            "error": "gh api failed",
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
        }
    try:
        return 0, json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return 1, {"error": f"invalid JSON from gh api: {exc}", "stdout": proc.stdout[:2000]}


def _pick_run_fields(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "display_title": run.get("display_title"),
        "workflow_id": run.get("workflow_id"),
        "run_number": run.get("run_number"),
        "run_attempt": run.get("run_attempt"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "html_url": run.get("html_url"),
        "actor": (run.get("actor") or {}).get("login"),
    }


def _pick_job_fields(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "run_id": job.get("run_id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "runner_name": job.get("runner_name"),
        "runner_group_name": job.get("runner_group_name"),
        "html_url": job.get("html_url"),
        "steps": [
            {
                "number": step.get("number"),
                "name": step.get("name"),
                "status": step.get("status"),
                "conclusion": step.get("conclusion"),
            }
            for step in job.get("steps", [])
        ],
    }


def collect(repo: str, run_id: int | None, branch: str | None, limit: int) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo": repo,
        "branch_filter": branch,
        "limit": limit,
        "notes": [
            "Sanitized diagnostic bundle: no secrets or environment values collected.",
            "startup_failure with zero jobs/steps indicates GitHub-side startup, billing, permissions, or workflow-registration failure before repo code executes.",
        ],
    }

    rc, permissions = _gh_api(f"repos/{repo}/actions/permissions")
    evidence["actions_permissions"] = {"rc": rc, "payload": permissions}

    rc, workflows = _gh_api(f"repos/{repo}/actions/workflows?per_page=100")
    evidence["workflows"] = {
        "rc": rc,
        "payload": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "path": item.get("path"),
                "state": item.get("state"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in (workflows.get("workflows", []) if isinstance(workflows, dict) else [])
        ],
    }

    runs_path = f"repos/{repo}/actions/runs?per_page={limit}"
    if branch:
        runs_path += f"&branch={quote(branch, safe='')}"
    rc, runs_payload = _gh_api(runs_path)
    runs = runs_payload.get("workflow_runs", []) if isinstance(runs_payload, dict) else []
    evidence["recent_runs"] = {"rc": rc, "payload": [_pick_run_fields(run) for run in runs]}

    if run_id is None and runs:
        run_id = runs[0].get("id")
    evidence["selected_run_id"] = run_id

    if run_id:
        rc, run = _gh_api(f"repos/{repo}/actions/runs/{run_id}")
        evidence["selected_run"] = {"rc": rc, "payload": _pick_run_fields(run) if isinstance(run, dict) else run}

        rc, jobs = _gh_api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
        job_payload = jobs.get("jobs", []) if isinstance(jobs, dict) else []
        evidence["selected_run_jobs"] = {"rc": rc, "count": len(job_payload), "payload": [_pick_job_fields(job) for job in job_payload]}

    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo, default: %(default)s")
    parser.add_argument("--run-id", type=int, help="specific Actions run ID to inspect")
    parser.add_argument("--branch", help="optional branch filter for recent runs")
    parser.add_argument("--limit", type=int, default=20, help="recent run count, max 100")
    parser.add_argument("--output", type=Path, help="write evidence JSON to this path")
    args = parser.parse_args(argv)

    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")

    evidence = collect(args.repo, args.run_id, args.branch, args.limit)
    text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
