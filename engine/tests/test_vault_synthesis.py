"""Tests for vault synthesis jobs (engine/vault/synthesis.py).

The LLM client is faked so these run offline and deterministically.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vault import paths, synthesis


class FakeClient:
    """Duck-typed stand-in for JarvisLLMClient with a recorded last call."""

    def __init__(self, *, success: bool = True, content: str = "## Connections\nok"):
        self._success = success
        self._content = content
        self.last_call: dict | None = None

    async def call(self, **kwargs):
        self.last_call = kwargs
        return SimpleNamespace(
            success=self._success,
            content=self._content,
            error=None if self._success else "boom",
        )


async def test_synthesis_brief_writes_inbox_note(tmp_path):
    paths.write_note(paths.SOURCES, "a.md", "institutional flows compress vol", root=tmp_path)
    paths.write_note(paths.THESES, "b.md", "vol will expand", root=tmp_path)
    client = FakeClient(content="## Connections\nfound a link")

    out = await synthesis.run_synthesis_brief(client, root=tmp_path, days=7)

    assert out is not None
    assert out.parent.name == paths.INBOX
    assert out.name.startswith("brief-")
    text = out.read_text(encoding="utf-8")
    assert "job: synthesis-brief" in text
    assert "found a link" in text
    assert client.last_call["agent_name"] == "vault_synthesis_brief"


async def test_synthesis_brief_skips_when_no_notes(tmp_path):
    client = FakeClient()
    out = await synthesis.run_synthesis_brief(client, root=tmp_path, days=7)
    assert out is None
    assert client.last_call is None  # LLM never called — no spend


async def test_synthesis_brief_returns_none_on_llm_failure(tmp_path):
    paths.write_note(paths.SOURCES, "a.md", "note", root=tmp_path)
    client = FakeClient(success=False)
    out = await synthesis.run_synthesis_brief(client, root=tmp_path, days=7)
    assert out is None


async def test_contradiction_check_requires_both_folders(tmp_path):
    # Only sources, no theses → skip without calling the LLM.
    paths.write_note(paths.SOURCES, "s.md", "data says X", root=tmp_path)
    client = FakeClient()
    out = await synthesis.run_contradiction_check(client, root=tmp_path, days=30)
    assert out is None
    assert client.last_call is None


async def test_contradiction_check_writes_report(tmp_path):
    paths.write_note(paths.THESES, "t.md", "X will rise", root=tmp_path)
    paths.write_note(paths.SOURCES, "s.md", "data shows X falling", root=tmp_path)
    client = FakeClient(content="t.md: source s.md contradicts — X is falling.")

    out = await synthesis.run_contradiction_check(client, root=tmp_path, days=30)

    assert out is not None
    assert out.name.startswith("contradictions-")
    text = out.read_text(encoding="utf-8")
    assert "job: contradiction-check" in text
    assert "contradicts" in text
    assert client.last_call["agent_name"] == "vault_contradiction_check"
