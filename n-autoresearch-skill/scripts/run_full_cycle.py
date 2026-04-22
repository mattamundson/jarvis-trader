#!/usr/bin/env python3
"""One-command runner: setup -> commit -> register -> train -> finalize -> dashboard."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DEFAULT = "http://localhost:3111"


def run(cmd: list[str], cwd: Path, capture: bool = False, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=check,
    )


def post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(base_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(base_url.rstrip("/") + path) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap_body(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("body"), dict):
        return result["body"]
    return result


def ensure_repo(repo_dir: Path) -> None:
    required = ["train.py", "prepare.py", "program.md"]
    missing = [name for name in required if not (repo_dir / name).exists()]
    if missing:
        raise SystemExit(f"Missing required repo files: {', '.join(missing)}")


def ensure_api(base_url: str) -> None:
    try:
        get(base_url, "/api/pool/list")
    except Exception as exc:
        raise SystemExit(f"Could not reach iii REST API at {base_url}: {exc}")


def branch_exists(repo_dir: Path, branch: str) -> bool:
    proc = run(["git", "rev-parse", "--verify", branch], cwd=repo_dir, capture=True, check=False)
    return proc.returncode == 0


def current_branch(repo_dir: Path) -> str:
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture=True).stdout.strip()


def ensure_branch(repo_dir: Path, tag: str) -> str:
    branch = f"autoresearch/{tag}"
    cur = current_branch(repo_dir)
    if cur == branch:
        return branch
    if branch_exists(repo_dir, branch):
        run(["git", "checkout", branch], cwd=repo_dir)
    else:
        run(["git", "checkout", "-b", branch], cwd=repo_dir)
    return branch


def maybe_setup_tag(base_url: str, tag: str) -> None:
    try:
        result = post(base_url, "/api/experiment/setup", {"tag": tag})
        body = unwrap_body(result)
        if body.get("error"):
            print(f"setup note: {body['error']}")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if "already exists" in payload:
            print(f"setup note: tag '{tag}' already exists")
        else:
            raise


def staged_train_diff_exists(repo_dir: Path) -> bool:
    proc = run(["git", "diff", "--quiet", "--", "train.py"], cwd=repo_dir, capture=False, check=False)
    return proc.returncode != 0


def commit_experiment(repo_dir: Path, message: str, allow_empty: bool) -> str:
    run(["git", "add", "train.py"], cwd=repo_dir)
    cmd = ["git", "commit", "-m", message]
    if allow_empty:
        cmd.insert(2, "--allow-empty")
    else:
        diff_proc = run(["git", "diff", "--cached", "--quiet", "--", "train.py"], cwd=repo_dir, check=False)
        if diff_proc.returncode == 0:
            raise SystemExit("No staged change detected in train.py. Use --baseline for an unchanged baseline run or edit train.py first.")
    run(cmd, cwd=repo_dir)
    return run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture=True).stdout.strip()


def register_experiment(base_url: str, tag: str, category: str, description: str, hypothesis: str, diff_summary: str, commit_sha: str, parent_id: str | None, gpu_id: str | None = None) -> str:
    payload: dict[str, Any] = {
        "tag": tag,
        "hypothesis": hypothesis,
        "description": description,
        "category": category,
        "commit_sha": commit_sha,
        "diff_summary": diff_summary,
        "parent_id": parent_id,
    }
    if gpu_id:
        payload["gpu_id"] = gpu_id
    result = post(base_url, "/api/experiment/register", payload)
    body = unwrap_body(result)
    experiment_id = body.get("experiment_id")
    if not experiment_id:
        raise SystemExit(f"Did not receive experiment_id from register response: {result}")
    return experiment_id


def train(repo_dir: Path, log_path: Path, cuda_visible_devices: str | None) -> int:
    env = os.environ.copy()
    if cuda_visible_devices is not None:
        env["CUDA_VISIBLE_DEVICES"] = cuda_visible_devices
    cmd = ["uv", "run", "train.py"]
    with log_path.open("w", encoding="utf-8", errors="replace") as f:
        proc = subprocess.run(cmd, cwd=repo_dir, env=env, text=True, stdout=f, stderr=subprocess.STDOUT, check=False)
    return proc.returncode


def finalize(repo_dir: Path, experiment_id: str, log_path: Path) -> dict[str, Any]:
    script = repo_dir / "scripts" / "finalize_experiment.py"
    proc = run([sys.executable, str(script), experiment_id, str(log_path)], cwd=repo_dir, capture=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"finalize_experiment.py failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


def dashboard(repo_dir: Path, tag: str) -> str:
    script = repo_dir / "scripts" / "status_dashboard.py"
    proc = run([sys.executable, str(script), "--tag", tag], cwd=repo_dir, capture=True)
    return proc.stdout


def maybe_apply_git_action(repo_dir: Path, finalize_result: dict[str, Any], no_auto_git_action: bool) -> str | None:
    body = unwrap_body(finalize_result)
    action = body.get("action")
    if no_auto_git_action or not action:
        return action
    if action == "git_reset":
        run(["git", "reset", "--hard", "HEAD~1"], cwd=repo_dir)
    return action


def write_status_note(repo_dir: Path, tag: str, experiment_id: str, description: str, hypothesis: str, log_path: Path, finalize_result: dict[str, Any], dashboard_text: str) -> Path:
    notes_dir = repo_dir / "status-notes"
    notes_dir.mkdir(exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out = notes_dir / f"{stamp}-{experiment_id}.md"
    body = unwrap_body(finalize_result)
    out.write_text(
        "\n".join([
            f"# Experiment status — {experiment_id}",
            "",
            f"- tag: {tag}",
            f"- experiment_id: {experiment_id}",
            f"- description: {description}",
            f"- hypothesis: {hypothesis}",
            f"- log_path: {log_path}",
            f"- action: {body.get('action')}",
            f"- improved: {body.get('improved')}",
            f"- status: {body.get('status')}",
            f"- best_val_bpb: {body.get('best_val_bpb')}",
            "",
            "## Dashboard snapshot",
            "```text",
            dashboard_text.rstrip(),
            "```",
            "",
        ]),
        encoding="utf-8",
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a full n-autoresearch experiment cycle.")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--category", required=True)
    ap.add_argument("--description", required=True)
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--diff-summary", required=True)
    ap.add_argument("--parent-id", default=None)
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--base-url", default=BASE_DEFAULT)
    ap.add_argument("--baseline", action="store_true", help="allow an unchanged baseline commit")
    ap.add_argument("--auto-setup", action="store_true", help="call setup and ensure autoresearch/<tag> branch exists")
    ap.add_argument("--cuda-visible-devices", default=None)
    ap.add_argument("--log-path", default=None)
    ap.add_argument("--no-auto-git-action", action="store_true", help="do not automatically apply keep/reset action")
    args = ap.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    ensure_repo(repo_dir)
    ensure_api(args.base_url)

    if args.auto_setup:
        maybe_setup_tag(args.base_url, args.tag)
        branch = ensure_branch(repo_dir, args.tag)
        print(f"Using branch: {branch}")

    commit_message = f"experiment: {args.description}"
    commit_sha = commit_experiment(repo_dir, commit_message, allow_empty=args.baseline)
    print(f"Committed: {commit_sha}")

    experiment_id = register_experiment(
        args.base_url,
        args.tag,
        args.category,
        args.description,
        args.hypothesis,
        args.diff_summary,
        commit_sha,
        args.parent_id,
    )
    print(f"Registered experiment_id: {experiment_id}")

    log_path = Path(args.log_path) if args.log_path else repo_dir / f"run-{experiment_id}.log"
    rc = train(repo_dir, log_path, args.cuda_visible_devices)
    print(f"Training process exited with code: {rc}")

    finalize_result = finalize(repo_dir, experiment_id, log_path)
    action = maybe_apply_git_action(repo_dir, finalize_result, args.no_auto_git_action)

    dash = dashboard(repo_dir, args.tag)
    status_note = write_status_note(repo_dir, args.tag, experiment_id, args.description, args.hypothesis, log_path, finalize_result, dash)

    print(json.dumps(finalize_result, indent=2))
    print(f"Applied git action: {action}")
    print(f"Status note: {status_note}")
    print(dash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
