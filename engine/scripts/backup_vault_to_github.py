"""backup_vault_to_github.py — midnight vault backup (#9).

Commits the Obsidian vault (a *separate* git repo at the vault root, NOT the
jarvis-trader repo) and pushes it to its private GitHub remote with the date as
the commit message. Off-device version history for every note, brief, and
contradiction report.

Gated by ENABLE_VAULT_BACKUP (default off), read fresh at run time.

Prerequisites (one-time, user action):
    cd ~/my-vault && git init && git remote add origin <private-repo-url>
    git config user.email / user.name; SSH key or PAT configured for push.

Usage:
    python scripts/backup_vault_to_github.py [--branch main] [--no-push] [--dry-run]
    Or scheduled in PM2 at 00:00 (see ecosystem.config.js: jarvis-vault-backup).
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("backup_vault_to_github")

_GIT_TIMEOUT = 120  # seconds per git invocation


def _enabled() -> bool:
    return os.getenv("ENABLE_VAULT_BACKUP", "0").strip().lower() in {"1", "true", "yes", "on"}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )


def _is_git_repo(root: Path) -> bool:
    if not root.exists():
        return False
    res = _git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    return res.returncode == 0 and res.stdout.strip() == "true"


def backup(root: Path, branch: str = "main", push: bool = True, dry_run: bool = False) -> int:
    """Stage, commit, and push the vault. Returns a process exit code.

    0 = success or nothing-to-commit; 1 = misconfiguration; 2 = git/push failure.
    """
    if not _is_git_repo(root):
        logger.error(
            "Vault at %s is not a git repo. Run: cd %s && git init && git remote add origin <url>",
            root,
            root,
        )
        return 1

    # Stage everything in the vault.
    if dry_run:
        status = _git(["status", "--porcelain"], cwd=root)
        changed = [ln for ln in status.stdout.splitlines() if ln.strip()]
        logger.info("[DRY-RUN] %d changed path(s) would be committed and %s.",
                    len(changed), "pushed" if push else "left local")
        return 0

    add = _git(["add", "-A"], cwd=root)
    if add.returncode != 0:
        logger.error("git add failed: %s", add.stderr.strip())
        return 2

    # Nothing staged? Then there is nothing to back up today — not an error.
    diff = _git(["diff", "--cached", "--quiet"], cwd=root)
    if diff.returncode == 0:
        logger.info("Vault clean — no changes to back up.")
        return 0

    staged = _git(["diff", "--cached", "--name-only"], cwd=root)
    file_count = len([ln for ln in staged.stdout.splitlines() if ln.strip()])

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    commit = _git(["commit", "-m", f"vault-backup-{date_str}"], cwd=root)
    if commit.returncode != 0:
        logger.error("git commit failed: %s", commit.stderr.strip() or commit.stdout.strip())
        return 2
    logger.info("Committed %d file(s): vault-backup-%s", file_count, date_str)

    if not push:
        logger.info("--no-push set — commit made locally, not pushed.")
        return 0

    pushed = _git(["push", "origin", branch], cwd=root)
    if pushed.returncode != 0:
        logger.error("git push failed: %s", pushed.stderr.strip())
        return 2
    logger.info("Pushed %d file(s) to origin/%s.", file_count, branch)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit + push the Obsidian vault.")
    parser.add_argument("--branch", default=os.getenv("VAULT_BACKUP_BRANCH", "main"))
    parser.add_argument("--no-push", action="store_true", help="Commit locally, do not push")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _enabled() and not args.dry_run:
        logger.info("ENABLE_VAULT_BACKUP not set — skipping vault backup.")
        return 0

    from vault import paths

    root = paths.vault_root()
    try:
        return backup(root, branch=args.branch, push=not args.no_push, dry_run=args.dry_run)
    except subprocess.TimeoutExpired:
        logger.error("git operation timed out after %ds", _GIT_TIMEOUT)
        return 2
    except Exception as exc:  # noqa: BLE001 — cron entry point, never crash the runner
        logger.exception("vault backup failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
