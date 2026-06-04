"""Tests for discord.hermes_upgrade.appliers.gepa_applier."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from discord.hermes_upgrade.appliers.gepa_applier import (
    GEPA_TARGETS_DIR,
    GepaApplier,
)
from discord.hermes_upgrade.models import BacklogEntry


def _entry(
    *,
    bookmark_id: str = "bm-gepa-1",
    title: str = "Recovery hardening for default profile",
    implementation_steps: list[str] | None = None,
    rationale: str = "improves robustness",
    extracted_content: str = "snippet",
    notes: str = "amo: review post-apply",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url="https://x.com/foo/status/1",
        source_discord_url="https://discord.com/channels/1/2/3",
        source_vault_path="raw/x-bookmarks/2026-W21.md",
        upgrade_type="gepa_target",
        title=title,
        rationale=rationale,
        implementation_steps=implementation_steps or ["step 1", "step 2"],
        leverage_rank=4,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content=extracted_content,
        notes=notes,
        tier="tier_2",
    )


# ---------------------------------------------------------------------------
# _slugify_title
# ---------------------------------------------------------------------------


def test_slugify_basic():
    applier = GepaApplier()
    assert (
        applier._slugify_title("Recovery hardening for default profile")
        == "recovery-hardening-for-default-profile"
    )


def test_slugify_unicode_and_special_chars():
    applier = GepaApplier()
    # Em-dash, slashes, parens, unicode arrow — all collapsed to single hyphens.
    result = applier._slugify_title("Hermes — GEPA / Phase 2 (auto→evolve)")
    assert result == "hermes-gepa-phase-2-auto-evolve"


def test_slugify_falls_back_to_default_for_empty():
    applier = GepaApplier()
    assert applier._slugify_title("") == "untitled-target"
    assert applier._slugify_title("---") == "untitled-target"


def test_slugify_truncates_to_60_chars():
    applier = GepaApplier()
    title = "x" * 200
    out = applier._slugify_title(title)
    assert len(out) <= 60


# ---------------------------------------------------------------------------
# _build_spec
# ---------------------------------------------------------------------------


def test_build_spec_shape():
    applier = GepaApplier()
    entry = _entry()
    spec = applier._build_spec(entry)

    assert set(spec.keys()) == {
        "metadata",
        "rationale",
        "implementation_steps",
        "dependencies",
        "extracted_content",
        "notes",
    }
    assert spec["metadata"]["title"] == entry.title
    assert spec["metadata"]["source_bookmark"] == entry.source_bookmark_url
    assert spec["metadata"]["source_discord"] == entry.source_discord_url
    assert spec["metadata"]["leverage_rank"] == entry.leverage_rank
    assert "created_at" in spec["metadata"]
    assert spec["rationale"] == entry.rationale
    assert spec["implementation_steps"] == entry.implementation_steps
    assert spec["notes"] == entry.notes


def test_build_spec_serializes_to_yaml_cleanly():
    """Sanity: the spec must round-trip through yaml.safe_dump/safe_load."""
    applier = GepaApplier()
    entry = _entry()
    spec = applier._build_spec(entry)
    rendered = yaml.safe_dump(spec, default_flow_style=False, sort_keys=False, allow_unicode=True)
    parsed = yaml.safe_load(rendered)
    assert parsed["metadata"]["title"] == entry.title


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


async def test_dry_run_returns_path_and_metadata():
    applier = GepaApplier()
    entry = _entry()
    out = await applier.dry_run(entry)
    assert "Would write GEPA target spec" in out
    assert GEPA_TARGETS_DIR in out
    assert "recovery-hardening-for-default-profile.yaml" in out
    assert entry.title in out


# ---------------------------------------------------------------------------
# apply — idempotency + write path
# ---------------------------------------------------------------------------


async def test_apply_short_circuits_when_file_exists():
    """First subprocess call returns EXISTS — apply must skip write."""
    applier = GepaApplier()
    entry = _entry()

    check_proc = MagicMock()
    check_proc.returncode = 0
    check_proc.communicate = AsyncMock(return_value=(b"EXISTS\n", b""))

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        AsyncMock(return_value=check_proc),
    ) as mock_exec:
        result = await applier.apply(entry)

    assert result.success is True
    assert result.notes == "idempotent skip"
    assert "already exists" in result.pre_apply_diff
    assert "recovery-hardening-for-default-profile.yaml" in result.rollback_path
    # Only the check call happened — no second exec for the heredoc write.
    assert mock_exec.call_count == 1


async def test_apply_writes_yaml_via_heredoc_when_missing():
    """File is missing — apply runs the heredoc write and returns success."""
    applier = GepaApplier()
    entry = _entry()

    check_proc = MagicMock()
    check_proc.returncode = 0
    check_proc.communicate = AsyncMock(return_value=(b"MISSING\n", b""))

    write_proc = MagicMock()
    write_proc.returncode = 0
    write_proc.communicate = AsyncMock(return_value=(b"OK\n", b""))

    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return check_proc if len(calls) == 1 else write_proc

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        side_effect=fake_exec,
    ):
        result = await applier.apply(entry)

    assert result.success is True
    assert "wrote" in result.pre_apply_diff
    assert "recovery-hardening-for-default-profile.yaml" in result.rollback_path
    assert result.rollback_path.startswith("rm -f ")

    # Inspect the heredoc command shape (second call = write).
    assert len(calls) == 2
    write_args = calls[1]
    assert write_args[0] == "wsl.exe"
    assert "-d" in write_args and "Ubuntu" in write_args
    assert "-u" in write_args and "mattm" in write_args
    bash_cmd = write_args[-1]
    assert "mkdir -p" in bash_cmd
    assert "cat >" in bash_cmd
    assert "<<'EOF_GEPA_TARGET_" in bash_cmd
    # YAML content must contain the title
    assert entry.title in bash_cmd


async def test_apply_reports_failure_on_nonzero_exit():
    applier = GepaApplier()
    entry = _entry()

    check_proc = MagicMock()
    check_proc.returncode = 0
    check_proc.communicate = AsyncMock(return_value=(b"MISSING\n", b""))

    write_proc = MagicMock()
    write_proc.returncode = 1
    write_proc.communicate = AsyncMock(return_value=(b"some error\n", b""))

    calls = {"n": 0}

    async def fake_exec(*args, **kwargs):
        calls["n"] += 1
        return check_proc if calls["n"] == 1 else write_proc

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        side_effect=fake_exec,
    ):
        result = await applier.apply(entry)

    assert result.success is False
    assert result.error is not None and "non-zero exit" in result.error


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


async def test_rollback_invokes_rm_f_command():
    applier = GepaApplier()
    entry = _entry()

    rm_proc = MagicMock()
    rm_proc.returncode = 0
    rm_proc.communicate = AsyncMock(return_value=(b"", b""))

    fake_result = MagicMock()
    fake_result.rollback_path = (
        f"rm -f {GEPA_TARGETS_DIR}/recovery-hardening-for-default-profile.yaml"
    )

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        AsyncMock(return_value=rm_proc),
    ) as mock_exec:
        ok = await applier.rollback(entry, fake_result)

    assert ok is True
    args, _ = mock_exec.call_args
    assert args[0] == "wsl.exe"
    assert "rm -f" in args[-1]
    assert "recovery-hardening-for-default-profile.yaml" in args[-1]


async def test_rollback_false_when_no_path_recorded():
    applier = GepaApplier()
    entry = _entry()
    fake_result = MagicMock()
    fake_result.rollback_path = ""
    ok = await applier.rollback(entry, fake_result)
    assert ok is False


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


async def test_verify_true_when_file_exists():
    applier = GepaApplier()
    entry = _entry()

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"OK\n", b""))

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        ok = await applier.verify(entry, MagicMock())
    assert ok is True


async def test_verify_false_when_file_missing():
    applier = GepaApplier()
    entry = _entry()

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"MISSING\n", b""))

    with patch(
        "discord.hermes_upgrade.appliers.gepa_applier.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        ok = await applier.verify(entry, MagicMock())
    assert ok is False


__all__: list[str] = []
