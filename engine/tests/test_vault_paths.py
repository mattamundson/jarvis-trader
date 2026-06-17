"""Tests for vault path/taxonomy helpers (engine/vault/paths.py)."""

from __future__ import annotations

import os
import time

from vault import paths


def test_ensure_folders_creates_taxonomy(tmp_path):
    root = paths.ensure_folders(tmp_path)
    assert root == tmp_path
    for folder in paths.VAULT_FOLDERS:
        assert (tmp_path / folder).is_dir()


def test_vault_root_honours_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_VAULT_ROOT", str(tmp_path / "custom-vault"))
    assert paths.vault_root() == tmp_path / "custom-vault"


def test_vault_root_default_when_unset(monkeypatch):
    monkeypatch.delenv("JARVIS_VAULT_ROOT", raising=False)
    assert paths.vault_root() == paths._DEFAULT_VAULT_ROOT


def test_write_and_read_note_roundtrip(tmp_path):
    out = paths.write_note(paths.INBOX, "hello.md", "# Hi\nbody", root=tmp_path)
    assert out == tmp_path / paths.INBOX / "hello.md"
    assert out.read_text(encoding="utf-8") == "# Hi\nbody"


def test_iter_recent_notes_filters_by_mtime(tmp_path):
    paths.ensure_folders(tmp_path)
    fresh = paths.write_note(paths.SOURCES, "fresh.md", "new", root=tmp_path)
    stale = paths.write_note(paths.SOURCES, "stale.md", "old", root=tmp_path)
    # Backdate the stale note 10 days.
    old_ts = time.time() - 10 * 86400
    os.utime(stale, (old_ts, old_ts))

    recent = paths.iter_recent_notes(paths.SOURCES, days=7, root=tmp_path)
    assert fresh in recent
    assert stale not in recent


def test_iter_recent_notes_missing_folder_returns_empty(tmp_path):
    assert paths.iter_recent_notes(paths.THESES, days=30, root=tmp_path) == []


def test_iter_recent_notes_recurses_subfolders(tmp_path):
    nested = tmp_path / paths.SOURCES / "2026-06-17"
    nested.mkdir(parents=True)
    (nested / "deep.md").write_text("nested", encoding="utf-8")
    recent = paths.iter_recent_notes(paths.SOURCES, days=7, root=tmp_path)
    assert any(p.name == "deep.md" for p in recent)


def test_read_notes_text_truncates_and_labels(tmp_path):
    paths.ensure_folders(tmp_path)
    note = paths.write_note(paths.THESES, "thesis.md", "x" * 100, root=tmp_path)
    block = paths.read_notes_text([note], max_chars_each=10, vault_base=tmp_path)
    assert "NOTE: 02-Theses/thesis.md" in block
    assert "[truncated]" in block
