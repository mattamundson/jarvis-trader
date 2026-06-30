"""Tests for the vault wikilink lint pass (engine/vault/lint.py).

Pure filesystem — no LLM, no network. Mirrors test_vault_paths.py.
"""

from __future__ import annotations

from vault import lint, paths


def _seed(tmp_path):
    # source-a links to thesis-x (valid, exists) and to ghost (broken).
    paths.write_note(
        paths.SOURCES,
        "source-a.md",
        "See [[thesis-x]] and the missing [[ghost note]].",
        root=tmp_path,
    )
    # thesis-x exists and is linked → not broken, not orphan.
    paths.write_note(paths.THESES, "thesis-x.md", "A documented position.", root=tmp_path)
    # lonely-orphan exists but nothing links to it → orphan.
    paths.write_note(paths.PROJECTS, "lonely-orphan.md", "Nobody references me.", root=tmp_path)


def test_lint_flags_broken_link(tmp_path):
    _seed(tmp_path)
    result = lint.lint_vault(root=tmp_path)
    targets = {b["target"] for b in result["broken"]}
    assert "ghost note" in targets
    # The valid link must NOT be reported as broken.
    assert "thesis-x" not in targets


def test_lint_flags_orphan(tmp_path):
    _seed(tmp_path)
    result = lint.lint_vault(root=tmp_path)
    assert "03-Projects/lonely-orphan.md" in result["orphans"]
    # A linked note is not an orphan.
    assert "02-Theses/thesis-x.md" not in result["orphans"]


def test_lint_link_resolution_ignores_alias_and_heading(tmp_path):
    paths.write_note(paths.THESES, "target.md", "body", root=tmp_path)
    paths.write_note(
        paths.SOURCES,
        "ref.md",
        "Alias [[target|see this]] and anchor [[Target#section]].",
        root=tmp_path,
    )
    result = lint.lint_vault(root=tmp_path)
    assert result["broken"] == []


def test_inbox_output_is_not_an_orphan(tmp_path):
    # Generated automation output lives in 00-Inbox and is excluded from orphans.
    paths.write_note(paths.INBOX, "brief-2026-01-01.md", "generated", root=tmp_path)
    paths.write_note(paths.SOURCES, "s.md", "no links here", root=tmp_path)
    result = lint.lint_vault(root=tmp_path)
    assert all("00-Inbox" not in o for o in result["orphans"])


def test_run_lint_writes_inbox_report(tmp_path):
    _seed(tmp_path)
    out = lint.run_lint(root=tmp_path)
    assert out is not None
    assert out.parent.name == paths.INBOX
    assert out.name.startswith("lint-")
    text = out.read_text(encoding="utf-8")
    assert "job: lint" in text
    assert "Broken links" in text
    assert "ghost note" in text


def test_run_lint_skips_empty_vault(tmp_path):
    out = lint.run_lint(root=tmp_path)
    assert out is None
