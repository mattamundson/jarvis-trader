"""Tests for the vault GitHub backup (engine/scripts/backup_vault_to_github.py).

Exercises the local git path only — never pushes to a real remote.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

backup_vault_to_github = pytest.importorskip("scripts.backup_vault_to_github")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=str(path), check=True)
    # Keep the throwaway repo hermetic — never invoke commit signing.
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(path), check=True)


def test_backup_errors_when_not_a_git_repo(tmp_path):
    (tmp_path / "00-Inbox").mkdir()
    rc = backup_vault_to_github.backup(tmp_path, push=False)
    assert rc == 1  # misconfiguration


def test_backup_commits_changes_locally(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "00-Inbox").mkdir()
    (tmp_path / "00-Inbox" / "note.md").write_text("hello", encoding="utf-8")

    rc = backup_vault_to_github.backup(tmp_path, push=False)
    assert rc == 0

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=str(tmp_path), capture_output=True, text=True
    )
    assert "vault-backup-" in log.stdout


def test_backup_clean_repo_is_noop(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(tmp_path), check=True)

    # No new changes → returns 0 without creating a second commit.
    rc = backup_vault_to_github.backup(tmp_path, push=False)
    assert rc == 0
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True
    )
    assert count.stdout.strip() == "1"


def test_dry_run_makes_no_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    rc = backup_vault_to_github.backup(tmp_path, push=False, dry_run=True)
    assert rc == 0
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=str(tmp_path), capture_output=True, text=True
    )
    assert log.returncode != 0 or log.stdout.strip() == ""  # no commits yet
