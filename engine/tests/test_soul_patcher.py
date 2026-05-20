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
                ),
            )
        assert ok is True
