"""Tests for SoulPatcher applier.

Mock-only — never touches the real ~/.hermes/SOUL.md files or invokes wsl.exe.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord.hermes_upgrade.appliers.soul_patcher import SOUL_PATH, SoulPatcher
from discord.hermes_upgrade.models import ApplyResult, BacklogEntry


def _make_entry(
    *,
    bookmark_id: str = "bm-soul-001",
    implementation_steps: list[str] | None = None,
    extracted_content: str = "",
    notes: str = "",
    title: str = "Soul update",
    rationale: str = "",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url="https://x.com/test/status/1",
        source_discord_url="https://discord.com/channels/1/2/3",
        source_vault_path="vault/test.md",
        upgrade_type="soul_template",
        title=title,
        rationale=rationale,
        implementation_steps=implementation_steps or [],
        leverage_rank=3,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content=extracted_content,
        notes=notes,
        tier="tier_1",
    )


def _mock_proc(returncode: int = 0, stdout: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


# ---------------------------------------------------------------------------
# _determine_profile — routing
# ---------------------------------------------------------------------------


class TestDetermineProfile:
    def test_routes_to_programmer(self) -> None:
        entry = _make_entry(notes="apply to programmer profile")
        assert SoulPatcher()._determine_profile(entry) == "programmer"

    def test_routes_to_researcher(self) -> None:
        entry = _make_entry(notes="this is for the researcher SOUL")
        assert SoulPatcher()._determine_profile(entry) == "researcher"

    def test_routes_to_designer(self) -> None:
        entry = _make_entry(rationale="The designer profile should learn this")
        assert SoulPatcher()._determine_profile(entry) == "designer"

    def test_falls_back_to_default(self) -> None:
        entry = _make_entry(notes="general improvement, no profile mentioned")
        assert SoulPatcher()._determine_profile(entry) == "default"

    def test_first_match_wins_when_multiple_profiles_mentioned(self) -> None:
        # programmer is checked first in the tuple iteration order.
        entry = _make_entry(notes="for programmer and researcher both")
        assert SoulPatcher()._determine_profile(entry) == "programmer"

    def test_routes_from_extracted_content(self) -> None:
        """profile keyword appears only in extracted_content (broadened scan)."""
        entry = _make_entry(
            notes="",
            title="System prompt template",
            rationale="",
            extracted_content="Use this persona template for the researcher profile.",
        )
        assert SoulPatcher()._determine_profile(entry) == "researcher"

    def test_routes_from_title_only(self) -> None:
        entry = _make_entry(title="Designer SOUL — UI guidelines")
        assert SoulPatcher()._determine_profile(entry) == "designer"


# ---------------------------------------------------------------------------
# _extract_soul_addition — fenced blocks + prose
# ---------------------------------------------------------------------------


class TestExtractSoulAddition:
    def test_finds_fenced_markdown_block(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "Here's the new section:\n"
                "```markdown\n"
                "## Trading discipline\n\n"
                "Never override the kill switch.\n"
                "```\n"
                "End of content."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "## Trading discipline" in out
        assert "kill switch" in out

    def test_finds_unannotated_fenced_block(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "```\n" "Always verify before reporting.\n" "API call > response > fact.\n" "```\n"
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "verify before reporting" in out

    def test_finds_section_with_header(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "Some preamble.\n"
                "\n"
                "## New SOUL guidance\n"
                "This is a multi-line section that should be picked up.\n"
                "It has enough length to clear the 20-char threshold.\n"
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "New SOUL guidance" in out

    def test_falls_back_to_extracted_prose(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "This is just a long paragraph of prose without any markdown fences "
                "or section headers but it should still be returned as a fallback."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "long paragraph of prose" in out

    def test_returns_none_when_nothing_substantive(self) -> None:
        entry = _make_entry(extracted_content="short", implementation_steps=[])
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is None

    # ------------------------------------------------------------------
    # New broadened LLM-output patterns
    # ------------------------------------------------------------------

    def test_extracts_soul_headed_section(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "Intro text here.\n\n"
                "# Soul\n"
                "You are an autonomous researcher. Your main job is to compound evidence.\n"
                "Refuse useless agreement.\n\n"
                "# Other section\n"
                "Not part of the SOUL block."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "autonomous researcher" in out
        assert "compound evidence" in out
        assert "# Other section" not in out

    def test_extracts_persona_headed_section(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "## Persona — Staff Engineer\n"
                "You operate as a senior staff engineer with veto power on architecture.\n"
                "You push back with evidence."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "staff engineer" in out.lower()
        assert "veto power" in out.lower()

    def test_extracts_operating_contract_section(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "Background prose.\n\n"
                "### Operating contract\n"
                "Claims vault schema, source plan structure, refresh cadence rules apply.\n"
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "operating contract" in out.lower()
        assert "claims vault" in out.lower()

    def test_append_this_intro_captures_following_block(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                (
                    "Append this to SOUL.md: You are a researcher who maintains a "
                    "structured vault of claims, findings, and dossiers. Always cite sources."
                ),
            ],
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "structured vault" in out
        assert "cite sources" in out

    def test_adopt_this_persona_intro_captures_following_block(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "Adopt this persona: You are a designer with a strict sense of "
                "visual hierarchy. You refuse to ship without contrast checks."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "visual hierarchy" in out

    def test_persona_prose_paragraph_capture(self) -> None:
        """Long 'you are a <role>' paragraph is captured even without headers/fences."""
        entry = _make_entry(
            extracted_content=(
                "Some context.\n\n"
                "You are a programmer who values tested code over clever code. "
                "Your main job is to ship correct, boring software.\n\n"
                "Other paragraph."
            ),
        )
        out = SoulPatcher()._extract_soul_addition(entry)
        assert out is not None
        assert "tested code" in out
        assert "Other paragraph" not in out


# ---------------------------------------------------------------------------
# dry_run — preview
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_returns_preview_with_profile_and_path(self) -> None:
        entry = _make_entry(
            notes="programmer profile",
            extracted_content=("```markdown\n" "Be ruthless about test discipline.\n" "```\n"),
        )
        out = await SoulPatcher().dry_run(entry)
        assert "profile=programmer" in out
        assert SOUL_PATH["programmer"] in out
        assert "Be ruthless about test discipline." in out
        assert f"hermes-upgrade:{entry.bookmark_id}" in out

    @pytest.mark.asyncio
    async def test_returns_error_when_no_addition(self) -> None:
        entry = _make_entry(extracted_content="too short")
        out = await SoulPatcher().dry_run(entry)
        assert out.startswith("ERROR")


# ---------------------------------------------------------------------------
# apply — idempotency + backup + append
# ---------------------------------------------------------------------------


class TestApply:
    @pytest.mark.asyncio
    async def test_short_circuits_when_marker_present(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "```markdown\n" "Add this discipline rule that is long enough to pass.\n" "```\n"
            ),
        )
        applier = SoulPatcher()
        # First WSL call is the marker check; return EXISTS to trigger short-circuit.
        proc = _mock_proc(returncode=0, stdout=b"EXISTS\n")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as mock_subproc:
            result = await applier.apply(entry)

        assert result.success is True
        assert "idempotent" in result.notes.lower()
        assert result.rollback_path == ""
        # Exactly ONE subprocess call (the check), no append.
        assert mock_subproc.call_count == 1

    @pytest.mark.asyncio
    async def test_creates_backup_and_appends_when_marker_missing(self) -> None:
        entry = _make_entry(
            notes="researcher profile",
            extracted_content=(
                "```markdown\n" "Always cite primary sources in research output.\n" "```\n"
            ),
        )
        applier = SoulPatcher()
        # Two WSL calls: marker check (MISSING) → append script (rc 0).
        check_proc = _mock_proc(returncode=0, stdout=b"MISSING\n")
        append_proc = _mock_proc(returncode=0, stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[check_proc, append_proc]),
        ) as mock_subproc:
            result = await applier.apply(entry)

        assert result.success is True
        assert result.rollback_path.startswith(SOUL_PATH["researcher"] + ".bak.")
        assert mock_subproc.call_count == 2

        # Second call must be the append script — verify shape.
        append_call_args = mock_subproc.call_args_list[1].args
        cmd = append_call_args[-1]
        assert "cp" in cmd  # backup
        assert "cat >>" in cmd  # append
        assert f"hermes-upgrade:{entry.bookmark_id}" in cmd
        # Target path must be the researcher SOUL.
        assert SOUL_PATH["researcher"] in cmd

    @pytest.mark.asyncio
    async def test_apply_returns_failure_when_addition_missing(self) -> None:
        entry = _make_entry(extracted_content="x")
        result = await SoulPatcher().apply(entry)
        assert result.success is False
        assert result.error == "could not extract SOUL addition"

    @pytest.mark.asyncio
    async def test_apply_returns_failure_when_append_nonzero(self) -> None:
        entry = _make_entry(
            extracted_content=(
                "```markdown\n" "A new piece of soul wisdom that is sufficiently long.\n" "```\n"
            ),
        )
        check_proc = _mock_proc(returncode=0, stdout=b"MISSING\n")
        append_proc = _mock_proc(returncode=5, stdout=b"cp: permission denied\n")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[check_proc, append_proc]),
        ):
            result = await SoulPatcher().apply(entry)
        assert result.success is False
        assert result.error is not None
        assert "exit=5" in result.error


# ---------------------------------------------------------------------------
# verify + rollback
# ---------------------------------------------------------------------------


class TestVerifyRollback:
    @pytest.mark.asyncio
    async def test_verify_true_when_grep_returns_ok(self) -> None:
        entry = _make_entry(
            extracted_content=("```markdown\nsomething substantial enough to extract\n```"),
        )
        proc = _mock_proc(returncode=0, stdout=b"OK\n")
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            ok = await SoulPatcher().verify(
                entry,
                ApplyResult(
                    bookmark_id=entry.bookmark_id,
                    success=True,
                    pre_apply_diff="",
                    post_apply_verification="",
                    rollback_path="",
                ),
            )
        assert ok is True

    @pytest.mark.asyncio
    async def test_verify_false_when_grep_returns_missing(self) -> None:
        entry = _make_entry(
            extracted_content=("```markdown\nsomething substantial enough to extract\n```"),
        )
        proc = _mock_proc(returncode=0, stdout=b"MISSING\n")
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            ok = await SoulPatcher().verify(
                entry,
                ApplyResult(
                    bookmark_id=entry.bookmark_id,
                    success=True,
                    pre_apply_diff="",
                    post_apply_verification="",
                    rollback_path="",
                ),
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_rollback_returns_false_when_no_backup_path(self) -> None:
        entry = _make_entry(
            extracted_content=("```markdown\nsomething substantial enough to extract\n```"),
        )
        ok = await SoulPatcher().rollback(
            entry,
            ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
            ),
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_rollback_restores_from_backup_path(self) -> None:
        entry = _make_entry(
            extracted_content=("```markdown\nsomething substantial enough to extract\n```"),
        )
        proc = _mock_proc(returncode=0, stdout=b"OK\n")
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            ok = await SoulPatcher().rollback(
                entry,
                ApplyResult(
                    bookmark_id=entry.bookmark_id,
                    success=True,
                    pre_apply_diff="",
                    post_apply_verification="",
                    rollback_path="/home/mattm/.hermes/SOUL.md.bak.20260101T000000Z",
                    notes="",
                ),
            )
        assert ok is True


# ---------------------------------------------------------------------------
# B11 regression — UTF-8 env passthrough to wsl.exe
# ---------------------------------------------------------------------------


class TestUtf8EnvPassthrough:
    """Locks in fix for the Unicode arrow (U+2192) crash in soul_template entries.

    Earlier behavior passed no env= kwarg to create_subprocess_exec, so the
    WSL subprocess inherited the parent's cp1252 codepage on Windows and
    crashed when the addition payload contained the right-arrow glyph. We
    now pass an explicit env with PYTHONIOENCODING=utf-8 + WSLENV forwarding.
    """

    @pytest.mark.asyncio
    async def test_run_wsl_passes_utf8_env(self) -> None:
        applier = SoulPatcher()
        proc = _mock_proc(returncode=0, stdout=b"EXISTS\n")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as mock_subproc:
            await applier._run_wsl("echo test")

        assert mock_subproc.call_count == 1
        kwargs = mock_subproc.call_args.kwargs
        assert "env" in kwargs, "env= kwarg missing — Unicode crash regression"
        env = kwargs["env"]
        assert env.get("PYTHONIOENCODING") == "utf-8"
        assert "PYTHONIOENCODING" in env.get(
            "WSLENV", ""
        ), "WSLENV must forward PYTHONIOENCODING into the WSL session"

    @pytest.mark.asyncio
    async def test_run_wsl_preserves_existing_env(self) -> None:
        """env passthrough should include the existing OS env, not replace it."""
        import os as _os

        # Plant a marker var that should survive the env merge
        marker_key = "JARVIS_B11_TEST_MARKER"
        marker_val = "preserved"
        _os.environ[marker_key] = marker_val
        try:
            applier = SoulPatcher()
            proc = _mock_proc(returncode=0, stdout=b"OK\n")
            with patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ) as mock_subproc:
                await applier._run_wsl("true")
            env = mock_subproc.call_args.kwargs["env"]
            assert env.get(marker_key) == marker_val
        finally:
            _os.environ.pop(marker_key, None)
