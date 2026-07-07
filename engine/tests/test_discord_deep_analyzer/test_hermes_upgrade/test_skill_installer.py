"""Tests for discord.hermes_upgrade.appliers.skill_installer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from discord.hermes_upgrade.appliers.skill_installer import SkillInstaller
from discord.hermes_upgrade.models import BacklogEntry


def _entry(
    *,
    bookmark_id: str = "bm-1",
    title: str = "test",
    implementation_steps: list[str] | None = None,
    extracted_content: str = "",
    notes: str = "",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url="https://x.com/foo/status/1",
        source_discord_url="https://discord.com/channels/1/2/3",
        source_vault_path="raw/x-bookmarks/2026-W21.md",
        upgrade_type="skill",
        title=title,
        rationale="r",
        implementation_steps=implementation_steps or [],
        leverage_rank=3,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content=extracted_content,
        notes=notes,
        tier="tier_1",
    )


# ---------------------------------------------------------------------------
# _extract_slug_or_url
# ---------------------------------------------------------------------------


def test_extract_parses_slug_from_install_command():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])
    assert installer._extract_slug_or_url(entry) == "foo/bar"


def test_extract_parses_slug_with_backticks():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["Run `hermes skill install owner/cool-skill`"])
    assert installer._extract_slug_or_url(entry) == "owner/cool-skill"


def test_extract_parses_github_url_from_extracted_content():
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["Some unrelated step"],
        extracted_content="See https://github.com/owner/repo for details",
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/owner/repo"


def test_extract_parses_github_dot_git_url():
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=[],
        extracted_content="git clone https://github.com/owner/repo.git",
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/owner/repo.git"


def test_extract_returns_none_when_no_match():
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["pip install something-unrelated"],
        extracted_content="no urls here",
    )
    assert installer._extract_slug_or_url(entry) is None


def test_install_token_takes_priority_over_url_in_content():
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["hermes skill install priority/wins"],
        extracted_content="ignored https://github.com/loser/repo",
    )
    assert installer._extract_slug_or_url(entry) == "priority/wins"


# ---------------------------------------------------------------------------
# _extract_slug_or_url — new patterns (broadened extractors)
# ---------------------------------------------------------------------------


def test_extract_finds_url_inside_implementation_step():
    """Pattern 2: github URL embedded in any implementation_step."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=[
            "Clone https://github.com/ghumare64/AgentMemory to /home/mattm/.hermes/skills/agent-memory/",
            "Install dependencies",
        ]
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/ghumare64/AgentMemory"


def test_extract_finds_url_in_notes():
    """Pattern 4: URL inside notes field."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["Visit the release page"],
        notes="See https://github.com/owner/repo for more info",
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/owner/repo"


def test_extract_clone_pattern_when_url_alone_missing():
    """Pattern 5: 'clone <url>' regex hit. Verifies the clone-keyword path works.

    The implementation_steps URL fallback (priority 2) catches the URL alone
    in most cases; this test verifies the clone-keyword path also works when
    the URL embeds trailing punctuation/parens that the bare URL regex would skip.
    """
    installer = SkillInstaller()
    # Backticks around the URL would defeat the bare-URL regex but the clone path catches it.
    entry = _entry(
        implementation_steps=["Run `git clone https://github.com/owner/repo` to grab the source"],
    )
    out = installer._extract_slug_or_url(entry)
    assert out is not None
    assert "github.com/owner/repo" in out


def test_extract_title_derived_slug():
    """Pattern 6: title shaped like org/repo is used when no URL is present."""
    installer = SkillInstaller()
    entry = _entry(
        title="ghumare64/AgentMemory",
        implementation_steps=["Install via skill manager"],
    )
    assert installer._extract_slug_or_url(entry) == "ghumare64/AgentMemory"


def test_extract_returns_none_when_title_is_freetext():
    """Pattern 6 only fires when the title matches the strict slug regex."""
    installer = SkillInstaller()
    entry = _entry(
        title="A skill for doing important things",
        implementation_steps=["Visit our website"],
    )
    assert installer._extract_slug_or_url(entry) is None


def test_extract_strips_dot_git_suffix_for_install_command():
    """Slug normalization: hermes skill install <X.git> -> <X>."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["hermes skill install https://github.com/owner/repo.git"],
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/owner/repo"


def test_extract_strips_query_string_for_install_command():
    """Slug normalization: hermes skill install <X?ref=Y> -> <X>."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["hermes skill install owner/repo?ref=main"],
    )
    assert installer._extract_slug_or_url(entry) == "owner/repo"


def test_extract_strips_surrounding_quotes_and_parens():
    """Slug normalization: strip quotes/parens from install token."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=['hermes skill install "owner/repo"'],
    )
    assert installer._extract_slug_or_url(entry) == "owner/repo"


def test_extract_priority_steps_url_over_extracted_content_url():
    """Pattern 2 (URL in step) beats pattern 3 (URL in extracted_content)."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["Clone https://github.com/winner/repo here"],
        extracted_content="loser https://github.com/loser/repo",
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/winner/repo"


def test_extract_priority_extracted_content_over_notes():
    """Pattern 3 beats pattern 4."""
    installer = SkillInstaller()
    entry = _entry(
        implementation_steps=["Visit website"],
        extracted_content="https://github.com/winner/repo",
        notes="https://github.com/loser/repo",
    )
    assert installer._extract_slug_or_url(entry) == "https://github.com/winner/repo"


# ---------------------------------------------------------------------------
# _slug_root
# ---------------------------------------------------------------------------


def test_slug_root_from_owner_repo():
    assert SkillInstaller()._slug_root("owner/repo") == "repo"


def test_slug_root_from_github_url():
    assert SkillInstaller()._slug_root("https://github.com/owner/repo") == "repo"


def test_slug_root_from_github_dot_git_url():
    assert SkillInstaller()._slug_root("https://github.com/owner/repo.git") == "repo"


def test_slug_root_trailing_slash():
    assert SkillInstaller()._slug_root("https://github.com/owner/repo/") == "repo"


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


async def test_dry_run_returns_expected_shape():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])
    out = await installer.dry_run(entry)
    assert "hermes skills install foo/bar" in out
    assert "hermes skills list" in out
    assert "grep -F bar" in out


async def test_dry_run_returns_error_when_no_target():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["something"], extracted_content="nothing")
    out = await installer.dry_run(entry)
    assert out.startswith("ERROR")
    assert entry.bookmark_id in out


# ---------------------------------------------------------------------------
# apply: idempotency + subprocess invocation
# ---------------------------------------------------------------------------


async def test_apply_returns_error_when_no_target():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=[], extracted_content="")
    result = await installer.apply(entry)
    assert result.success is False
    assert result.error is not None and "no skill slug" in result.error


async def test_apply_idempotent_skip_when_already_installed():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    async def fake_list_skills():
        return ["foo/bar", "another/skill"]

    with patch.object(installer, "_list_installed_skills", side_effect=fake_list_skills):
        result = await installer.apply(entry)

    assert result.success is True
    assert result.notes == "idempotent skip"
    assert "already installed" in result.pre_apply_diff


async def test_apply_invokes_wsl_subprocess_when_not_installed():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"installed bar v1.0\n", b""))

    async def fake_list():
        return ["unrelated/other"]

    with (
        patch.object(installer, "_list_installed_skills", side_effect=fake_list),
        patch(
            "discord.hermes_upgrade.appliers.skill_installer.asyncio.create_subprocess_exec",
            AsyncMock(return_value=fake_proc),
        ) as mock_exec,
    ):
        result = await installer.apply(entry)

    assert result.success is True
    assert result.rollback_path == "hermes skills uninstall foo/bar"
    assert "installed bar v1.0" in result.notes

    args, _ = mock_exec.call_args
    assert args[0] == "wsl.exe"
    assert "-d" in args and "Ubuntu" in args
    assert "-u" in args and "mattm" in args
    # bash command is the last positional arg
    assert "hermes skills install --yes 'foo/bar' 2>&1" in args[-1]


async def test_apply_records_failure_on_nonzero_exit():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.communicate = AsyncMock(return_value=(b"error: not found\n", b""))

    async def fake_list():
        return []

    with (
        patch.object(installer, "_list_installed_skills", side_effect=fake_list),
        patch(
            "discord.hermes_upgrade.appliers.skill_installer.asyncio.create_subprocess_exec",
            AsyncMock(return_value=fake_proc),
        ),
    ):
        result = await installer.apply(entry)

    assert result.success is False
    assert result.error is not None and "non-zero exit" in result.error


async def test_apply_handles_timeout():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(side_effect=TimeoutError())

    async def fake_list():
        return []

    with (
        patch.object(installer, "_list_installed_skills", side_effect=fake_list),
        patch(
            "discord.hermes_upgrade.appliers.skill_installer.asyncio.create_subprocess_exec",
            AsyncMock(return_value=fake_proc),
        ),
        patch(
            "discord.hermes_upgrade.appliers.skill_installer.asyncio.wait_for",
            AsyncMock(side_effect=__import__("asyncio").TimeoutError()),
        ),
    ):
        result = await installer.apply(entry)

    assert result.success is False
    assert result.error is not None and "timed out" in result.error


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


async def test_verify_true_when_skill_in_list():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    async def fake_list():
        return ["foo/bar v1.0"]

    with patch.object(installer, "_list_installed_skills", side_effect=fake_list):
        ok = await installer.verify(entry, MagicMock())
    assert ok is True


async def test_verify_false_when_skill_not_in_list():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    async def fake_list():
        return ["other/thing"]

    with patch.object(installer, "_list_installed_skills", side_effect=fake_list):
        ok = await installer.verify(entry, MagicMock())
    assert ok is False


async def test_verify_false_when_no_target():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=[], extracted_content="")
    ok = await installer.verify(entry, MagicMock())
    assert ok is False


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


async def test_rollback_invokes_uninstall():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=["hermes skill install foo/bar"])

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"uninstalled\n", b""))

    with patch(
        "discord.hermes_upgrade.appliers.skill_installer.asyncio.create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        ok = await installer.rollback(entry, MagicMock())

    assert ok is True
    args, _ = mock_exec.call_args
    assert "hermes skills uninstall 'foo/bar'" in args[-1]


async def test_rollback_false_when_no_target():
    installer = SkillInstaller()
    entry = _entry(implementation_steps=[], extracted_content="")
    ok = await installer.rollback(entry, MagicMock())
    assert ok is False


# pytest-asyncio auto mode handles the coroutine; no marker needed.
__all__: list[str] = []
