"""Hermetic tests for the source-integrity guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

GUARD_PATH = Path(__file__).resolve().parents[2] / "scripts" / "source_integrity_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("_source_integrity_guard_under_test", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _materialize_valid_repo(root: Path) -> None:
    guard = _load_guard()
    for kind, rel_path in guard.REQUIRED_PATHS:
        path = root / rel_path
        if kind == "dir":
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# test fixture\n", encoding="utf-8")

    git_dir = root / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")

    workflow = root / ".github" / "workflows" / "ci.yml"
    workflow.write_text(
        "name: ci\njobs:\n  check:\n    steps:\n      - uses: ./.github/actions/free-disk-space\n",
        encoding="utf-8",
    )
    action = root / ".github" / "actions" / "free-disk-space"
    action.mkdir(parents=True)
    (action / "action.yml").write_text("name: free disk space\nruns:\n  using: composite\n", encoding="utf-8")


def test_valid_synthetic_repo_has_no_findings(tmp_path):
    guard = _load_guard()
    _materialize_valid_repo(tmp_path)

    assert guard.scan(tmp_path) == []


def test_config_only_git_directory_fails(tmp_path):
    guard = _load_guard()
    _materialize_valid_repo(tmp_path)
    for child in (tmp_path / ".git").iterdir():
        if child.is_dir():
            for nested in child.rglob("*"):
                if nested.is_file():
                    nested.unlink()
            child.rmdir()
        elif child.name != "config":
            child.unlink()

    findings = guard.scan(tmp_path)

    assert any(finding.check == "git_metadata" and "HEAD" in finding.path for finding in findings)
    assert any(finding.check == "git_metadata" and "objects" in finding.path for finding in findings)
    assert any(finding.check == "git_metadata" and "refs" in finding.path for finding in findings)


def test_missing_required_source_path_fails(tmp_path):
    guard = _load_guard()
    _materialize_valid_repo(tmp_path)
    (tmp_path / "engine" / "main.py").unlink()

    findings = guard.scan(tmp_path)

    assert any(finding.check == "required_path" and finding.path == "engine/main.py" for finding in findings)


def test_missing_local_workflow_action_fails(tmp_path):
    guard = _load_guard()
    _materialize_valid_repo(tmp_path)
    (tmp_path / ".github" / "actions" / "free-disk-space" / "action.yml").unlink()

    findings = guard.scan(tmp_path)

    assert any(finding.check == "local_workflow_action" for finding in findings)
