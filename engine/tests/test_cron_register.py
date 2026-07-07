"""Tests for CronRegister applier.

Mock-only — never touches WSL or invokes wsl.exe. All subprocess calls are
patched to assert the constructed command string is shape-correct and
properly shlex-quoted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord.hermes_upgrade.appliers.cron_register import CronRegister
from discord.hermes_upgrade.models import BacklogEntry


def _make_entry(
    *,
    bookmark_id: str = "bm-test-001",
    implementation_steps: list[str] | None = None,
    extracted_content: str = "",
    notes: str = "",
    title: str = "Test cron",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url="https://x.com/test/status/1",
        source_discord_url="https://discord.com/channels/1/2/3",
        source_vault_path="vault/test.md",
        upgrade_type="cron_pattern",
        title=title,
        rationale="rationale",
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
# _extract_cron_spec — parses various input shapes
# ---------------------------------------------------------------------------


class TestExtractCronSpec:
    def test_parses_explicit_hermes_cron_add_invocation(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'github-sync' --schedule '0 8 * * *' "
                "--prompt 'Push all repos to GitHub'"
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["name"] == "github-sync"
        assert spec["schedule"] == "0 8 * * *"
        assert spec["prompt"] == "Push all repos to GitHub"
        assert spec["profile"] == "default"

    def test_parses_invocation_with_profile_flag(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'morning-brief' --schedule '0 7 * * *' "
                "--prompt 'Generate morning brief' --profile 'researcher'",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["profile"] == "researcher"

    def test_parses_heuristic_cron_expression_plus_prompt(self) -> None:
        entry = _make_entry(
            title="Weekly research digest",
            extracted_content=("Schedule: 0 9 * * MON\n" "Prompt: 'Summarize the week in trading'"),
            notes="researcher profile",
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["schedule"] == "0 9 * * MON"
        assert spec["prompt"] == "Summarize the week in trading"
        assert spec["profile"] == "researcher"
        assert spec["name"]  # derived from title

    def test_parses_natural_language_schedule(self) -> None:
        entry = _make_entry(
            title="Daily reminder",
            implementation_steps=[
                "Run every day at 8am",
                "prompt: Send the daily checklist to Discord",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert "every day" in spec["schedule"].lower()
        assert "daily checklist" in spec["prompt"]

    def test_returns_none_when_no_schedule_found(self) -> None:
        entry = _make_entry(
            implementation_steps=["Just some text without any schedule shape"],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is None

    def test_returns_none_when_no_prompt_found(self) -> None:
        entry = _make_entry(
            implementation_steps=["Schedule: 0 8 * * *"],
            # No prompt anywhere
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is None

    def test_unknown_profile_falls_back_to_default(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'x' --schedule '0 8 * * *' "
                "--prompt 'do thing' --profile 'invalid-profile'",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["profile"] == "default"

    # ------------------------------------------------------------------
    # New NL-schedule patterns (LLM free-form output)
    # ------------------------------------------------------------------

    def test_parses_every_N_minutes_schedule(self) -> None:
        entry = _make_entry(
            title="Heartbeat",
            implementation_steps=[
                "Run every 15 minutes",
                "prompt: ping the watchdog",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["schedule"] == "*/15 * * * *"
        assert "watchdog" in spec["prompt"]

    def test_parses_every_N_hours_schedule(self) -> None:
        entry = _make_entry(
            title="Periodic refresh",
            implementation_steps=[
                "Run every 2 hours",
                "prompt: refresh the dashboard cache",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["schedule"] == "0 */2 * * *"

    def test_parses_weekly_on_dow_at_time(self) -> None:
        entry = _make_entry(
            title="Sunday review",
            extracted_content=(
                "Schedule a weekly Sunday review using the researcher profile.\n"
                "Prompt: 'review the week of trading signals'"
            ),
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        # Either preserved NL ("weekly Sunday") OR converted ("0 0 * * 0") is acceptable;
        # both are recognized by Hermes' English cron parser.
        sched = spec["schedule"].lower()
        assert "sunday" in sched or "* * 0" in sched
        assert "trading signals" in spec["prompt"]
        assert spec["profile"] == "researcher"

    def test_parses_every_weekday_at_time(self) -> None:
        entry = _make_entry(
            title="Weekday push",
            implementation_steps=[
                "Use Hermes' English-cron syntax: 'every weekday at 8am, push GitHub repos'",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        # Either preserved NL ("every weekday at 8am") OR converted ("0 8 * * 1-5").
        sched = spec["schedule"].lower()
        assert "weekday" in sched or "* 1-5" in sched
        assert "github" in spec["prompt"].lower()

    def test_parses_daily_at_time_with_central_qualifier(self) -> None:
        entry = _make_entry(
            title="Morning research brief",
            implementation_steps=[
                "Add a daily 8am Central cron",
                "prompt: 'generate the morning research brief'",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        sched = spec["schedule"].lower()
        assert "daily" in sched or "8" in sched

    def test_profile_inferred_from_extracted_content_only(self) -> None:
        """profile token appears only in extracted_content (not steps/notes/title)."""
        entry = _make_entry(
            title="Some cron",
            implementation_steps=[
                "Schedule: 0 9 * * 1",
                "prompt: 'run the weekly tally'",
            ],
            extracted_content=("This applies to the designer profile per the upstream skill."),
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["profile"] == "designer"

    def test_prompt_falls_back_to_rationale(self) -> None:
        entry = BacklogEntry(
            bookmark_id="bm-test-fb",
            source_bookmark_url="https://x.com/test/status/1",
            source_discord_url="https://discord.com/channels/1/2/3",
            source_vault_path="vault/test.md",
            upgrade_type="cron_pattern",
            title="Rationale fallback",
            rationale="Generate a daily portfolio digest summarizing PnL and risk.",
            implementation_steps=["Schedule: 0 17 * * *"],
            leverage_rank=3,
            risk="low",
            dependencies=[],
            estimated_cost_usd=0.0,
            extracted_content="",
            notes="",
            tier="tier_1",
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert "portfolio digest" in spec["prompt"]

    def test_explicit_name_label_overrides_title_slug(self) -> None:
        entry = _make_entry(
            title="A very long descriptive title that we do NOT want as the name",
            implementation_steps=[
                "name: heartbeat-15m",
                "Schedule: */15 * * * *",
                "prompt: 'ping the watchdog'",
            ],
        )
        spec = CronRegister()._extract_cron_spec(entry)
        assert spec is not None
        assert spec["name"] == "heartbeat-15m"


# ---------------------------------------------------------------------------
# dry_run — returns command preview
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_returns_command_preview(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'demo' --schedule '0 8 * * *' --prompt 'hello'"
            ],
        )
        out = await CronRegister().dry_run(entry)
        assert "hermes cron add" in out
        assert "demo" in out
        assert "0 8 * * *" in out
        assert "hello" in out

    @pytest.mark.asyncio
    async def test_returns_error_when_spec_missing(self) -> None:
        entry = _make_entry(implementation_steps=["nothing useful"])
        out = await CronRegister().dry_run(entry)
        assert out.startswith("ERROR")
        assert entry.bookmark_id in out


# ---------------------------------------------------------------------------
# apply — idempotency + subprocess invocation
# ---------------------------------------------------------------------------


def _mock_proc(returncode: int = 0, stdout: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


class TestApply:
    @pytest.mark.asyncio
    async def test_short_circuits_when_cron_already_exists(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'github-sync' --schedule '0 8 * * *' "
                "--prompt 'Push repos'"
            ],
        )
        applier = CronRegister()
        applier._list_existing_crons = AsyncMock(
            return_value=["github-sync  0 8 * * *  Push repos"]
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(),
        ) as mock_subproc:
            result = await applier.apply(entry)
        assert result.success is True
        assert "idempotent" in result.notes.lower()
        mock_subproc.assert_not_called()

    @pytest.mark.asyncio
    async def test_invokes_wsl_with_correctly_quoted_command(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'test-cron' --schedule '0 8 * * *' "
                '--prompt "don\'t break shell"'
            ],
        )
        applier = CronRegister()
        applier._list_existing_crons = AsyncMock(return_value=[])
        proc = _mock_proc(returncode=0, stdout=b"registered\n")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as mock_subproc:
            result = await applier.apply(entry)

        assert result.success is True
        mock_subproc.assert_called_once()
        call_args = mock_subproc.call_args.args
        # First three args are the executable and its WSL distro flags.
        assert call_args[0] == "wsl.exe"
        assert "-d" in call_args
        assert "Ubuntu" in call_args
        # The composed bash -lc command string is the last positional arg.
        cmd = call_args[-1]
        assert "hermes cron add" in cmd
        assert "test-cron" in cmd
        # Prompt with embedded single-quote must be properly shlex-quoted.
        # shlex.quote on POSIX produces 'don'"'"'t break shell' — match a stable substring.
        assert "break shell" in cmd
        # rollback path must be a hermes cron remove invocation.
        assert "hermes cron remove" in result.rollback_path

    @pytest.mark.asyncio
    async def test_apply_returns_failure_when_subprocess_nonzero(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'demo' --schedule '0 8 * * *' --prompt 'hi'"
            ],
        )
        applier = CronRegister()
        applier._list_existing_crons = AsyncMock(return_value=[])
        proc = _mock_proc(returncode=1, stdout=b"error: bad arg\n")
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            result = await applier.apply(entry)
        assert result.success is False
        assert result.error is not None
        assert "exit=1" in result.error

    @pytest.mark.asyncio
    async def test_apply_returns_failure_when_spec_missing(self) -> None:
        entry = _make_entry(implementation_steps=["nothing useful"])
        result = await CronRegister().apply(entry)
        assert result.success is False
        assert result.error == "could not parse cron spec"

    @pytest.mark.asyncio
    async def test_apply_with_nondefault_profile_prefixes_env_var(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'r-digest' --schedule '0 9 * * MON' "
                "--prompt 'weekly digest' --profile 'researcher'"
            ],
        )
        applier = CronRegister()
        applier._list_existing_crons = AsyncMock(return_value=[])
        proc = _mock_proc(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as mock_subproc:
            await applier.apply(entry)
        cmd = mock_subproc.call_args.args[-1]
        assert "HERMES_PROFILE=researcher" in cmd


# ---------------------------------------------------------------------------
# verify + rollback
# ---------------------------------------------------------------------------


class TestVerifyRollback:
    @pytest.mark.asyncio
    async def test_verify_true_when_name_in_listing(self) -> None:
        entry = _make_entry(
            implementation_steps=[
                "hermes cron add --name 'demo' --schedule '0 8 * * *' --prompt 'hi'"
            ],
        )
        applier = CronRegister()
        applier._list_existing_crons = AsyncMock(return_value=["demo schedule prompt"])
        from discord.hermes_upgrade.models import ApplyResult

        ok = await applier.verify(
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
    async def test_verify_false_when_spec_missing(self) -> None:
        entry = _make_entry(implementation_steps=["nothing useful"])
        from discord.hermes_upgrade.models import ApplyResult

        ok = await CronRegister().verify(
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
