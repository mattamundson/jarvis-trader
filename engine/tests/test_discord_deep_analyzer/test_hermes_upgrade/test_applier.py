"""Tests for the Phase 3 Hermes upgrade orchestrator (applier.py).

Uses a MockApplier so tests don't depend on per-type appliers being built.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from discord.hermes_upgrade import applier as applier_module
from discord.hermes_upgrade.applier import (
    _get_applier,
    append_applied_log,
    apply_many,
    apply_one,
    load_backlog,
    save_backlog,
)
from discord.hermes_upgrade.appliers.base import BaseApplier
from discord.hermes_upgrade.models import ApplyResult, BacklogEntry, UpgradeType

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_entry(
    bookmark_id: str = "bk1",
    *,
    upgrade_type: UpgradeType = "skill",
    tier: str = "tier_1",
    risk: str = "low",
    apply_status: str = "pending",
    title: str = "Test entry",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url=f"https://x.com/test/{bookmark_id}",
        source_discord_url=f"https://discord.com/channels/0/0/{bookmark_id}",
        source_vault_path=f"vault/{bookmark_id}.md",
        upgrade_type=upgrade_type,
        title=title,
        rationale="because tests",
        implementation_steps=["echo install"],
        leverage_rank=4,
        risk=risk,  # type: ignore[arg-type]
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content="snippet",
        notes="",
        tier=tier,  # type: ignore[arg-type]
        apply_status=apply_status,  # type: ignore[arg-type]
    )


class MockApplier(BaseApplier):
    """Records calls so tests can assert lifecycle invariants without filesystem effects."""

    upgrade_type: UpgradeType = "skill"

    def __init__(
        self,
        *,
        success: bool = True,
        verify_ok: bool = True,
        diff: str = "echo mock-diff",
    ) -> None:
        self.success = success
        self.verify_ok = verify_ok
        self.diff = diff
        self.calls: list[str] = []

    async def dry_run(self, entry: BacklogEntry) -> str:
        self.calls.append("dry_run")
        return self.diff

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        self.calls.append("apply")
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=self.success,
            pre_apply_diff=self.diff,
            post_apply_verification="mock verified",
            rollback_path="git revert HEAD",
            notes="mock-apply-ok" if self.success else "mock-apply-failed",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        self.calls.append("verify")
        return self.verify_ok

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        self.calls.append("rollback")
        return True


@pytest.fixture
def patch_applier(monkeypatch) -> Iterator[MockApplier]:
    """Install a single MockApplier for every upgrade_type used in tests."""
    mock = MockApplier()
    monkeypatch.setattr(applier_module, "_get_applier", lambda _ut: mock)
    yield mock


# ---------------------------------------------------------------------------
# Persistence: load_backlog / save_backlog roundtrip
# ---------------------------------------------------------------------------


def test_load_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "backlog.jsonl"
    entries = [_make_entry("a"), _make_entry("b", upgrade_type="mcp_server", tier="tier_2")]
    save_backlog(entries, path)

    loaded = load_backlog(path)
    assert len(loaded) == 2
    assert loaded[0].bookmark_id == "a"
    assert loaded[1].upgrade_type == "mcp_server"
    assert loaded[1].tier == "tier_2"


def test_load_backlog_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "backlog.jsonl"
    entries = [_make_entry("a")]
    save_backlog(entries, path)
    # Append a blank line — should be ignored
    with path.open("a", encoding="utf-8") as f:
        f.write("\n\n")
    loaded = load_backlog(path)
    assert len(loaded) == 1


# ---------------------------------------------------------------------------
# applied.jsonl audit log
# ---------------------------------------------------------------------------


def test_append_applied_log_creates_file_with_timestamp(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "applied.jsonl"
    result = ApplyResult(
        bookmark_id="bk1",
        success=True,
        pre_apply_diff="diff",
        post_apply_verification="ok",
        rollback_path="git revert HEAD",
        notes="done",
    )
    append_applied_log(result, log_path)

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["bookmark_id"] == "bk1"
    assert record["success"] is True
    assert "timestamp" in record and "T" in record["timestamp"]


def test_append_applied_log_appends_multiple(tmp_path: Path) -> None:
    log_path = tmp_path / "applied.jsonl"
    for bid in ("a", "b", "c"):
        result = ApplyResult(
            bookmark_id=bid,
            success=True,
            pre_apply_diff="",
            post_apply_verification="",
            rollback_path="",
        )
        append_applied_log(result, log_path)
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    ids = [json.loads(line)["bookmark_id"] for line in lines]
    assert ids == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Idempotency + skip semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_one_short_circuits_when_already_applied(patch_applier: MockApplier) -> None:
    entry = _make_entry(apply_status="applied")
    entry.rollback_path = "previous-rollback"
    result = await apply_one(entry, auto_approve=True)

    assert result.success is True
    assert "already applied" in result.notes.lower()
    assert result.rollback_path == "previous-rollback"
    # The mock should NOT have been invoked
    assert patch_applier.calls == []


@pytest.mark.asyncio
async def test_apply_one_returns_skipped_for_skipped_entry(patch_applier: MockApplier) -> None:
    entry = _make_entry(apply_status="skipped")
    result = await apply_one(entry, auto_approve=True)

    assert result.success is False
    assert "skipped" in result.notes.lower()
    assert patch_applier.calls == []


@pytest.mark.asyncio
async def test_apply_one_user_declines_via_stdin(
    monkeypatch: pytest.MonkeyPatch, patch_applier: MockApplier
) -> None:
    entry = _make_entry()
    # Simulate user typing "n"
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    result = await apply_one(entry, auto_approve=False)

    assert result.success is False
    assert "skipped" in result.notes.lower()
    # dry_run ran, apply did not
    assert "dry_run" in patch_applier.calls
    assert "apply" not in patch_applier.calls


@pytest.mark.asyncio
async def test_apply_one_auto_approve_runs_full_lifecycle(patch_applier: MockApplier) -> None:
    entry = _make_entry()
    result = await apply_one(entry, auto_approve=True)

    assert result.success is True
    assert patch_applier.calls == ["dry_run", "apply", "verify"]
    assert result.rollback_path == "git revert HEAD"


@pytest.mark.asyncio
async def test_apply_one_dry_run_only_does_not_apply(patch_applier: MockApplier) -> None:
    entry = _make_entry()
    result = await apply_one(entry, dry_run_only=True)

    assert result.success is True
    assert "dry-run" in result.notes.lower()
    # Only dry_run was called
    assert patch_applier.calls == ["dry_run"]


@pytest.mark.asyncio
async def test_apply_one_verify_failure_flips_success(monkeypatch: pytest.MonkeyPatch) -> None:
    failing_verify = MockApplier(verify_ok=False)
    monkeypatch.setattr(applier_module, "_get_applier", lambda _ut: failing_verify)

    entry = _make_entry()
    result = await apply_one(entry, auto_approve=True)

    assert result.success is False
    assert "verification failed" in result.notes.lower()


# ---------------------------------------------------------------------------
# apply_many filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_many_filters_by_tier(tmp_path: Path, patch_applier: MockApplier) -> None:
    entries = [
        _make_entry("a", tier="tier_1"),
        _make_entry("b", tier="tier_2"),
        _make_entry("c", tier="tier_3"),
    ]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        tier_filter="tier_1",
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert len(results) == 1
    assert results[0].bookmark_id == "a"


@pytest.mark.asyncio
async def test_apply_many_filters_by_upgrade_type(
    tmp_path: Path, patch_applier: MockApplier
) -> None:
    entries = [
        _make_entry("a", upgrade_type="skill"),
        _make_entry("b", upgrade_type="mcp_server"),
        _make_entry("c", upgrade_type="cron_pattern"),
    ]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        upgrade_type_filter="mcp_server",
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert len(results) == 1
    assert results[0].bookmark_id == "b"


@pytest.mark.asyncio
async def test_apply_many_filters_by_bookmark_id(
    tmp_path: Path, patch_applier: MockApplier
) -> None:
    entries = [_make_entry("a"), _make_entry("b"), _make_entry("c")]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        bookmark_id_filter="c",
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert len(results) == 1
    assert results[0].bookmark_id == "c"


@pytest.mark.asyncio
async def test_apply_many_skips_non_applicable_entries(
    tmp_path: Path, patch_applier: MockApplier
) -> None:
    entries = [
        _make_entry("a", apply_status="pending"),
        _make_entry("b", apply_status="applied"),  # should be skipped
        _make_entry("c", apply_status="rolled_back"),  # should be skipped
        _make_entry("d", apply_status="failed"),  # eligible — re-attempt
    ]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    ids = [r.bookmark_id for r in results]
    assert ids == ["a", "d"]


@pytest.mark.asyncio
async def test_apply_many_persists_state_and_appends_log(
    tmp_path: Path, patch_applier: MockApplier
) -> None:
    entries = [_make_entry("a")]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    await apply_many(
        entries,
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    # State updated
    reloaded = load_backlog(backlog_path)
    assert reloaded[0].apply_status == "applied"
    assert reloaded[0].apply_timestamp is not None
    assert reloaded[0].rollback_path == "git revert HEAD"

    # Audit log written
    log_lines = applied_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1
    record = json.loads(log_lines[0])
    assert record["bookmark_id"] == "a"
    assert record["success"] is True


@pytest.mark.asyncio
async def test_apply_many_auto_approve_only_applies_to_tier1_low_risk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tier_2 / med-risk entries must still gate on stdin even when auto-approve-low-risk is on."""
    mock = MockApplier()
    monkeypatch.setattr(applier_module, "_get_applier", lambda _ut: mock)

    # User-input gating: simulate "n" so non-eligible entries get user-skipped
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    entries = [
        _make_entry("low1", tier="tier_1", risk="low"),
        _make_entry("med1", tier="tier_1", risk="med"),
        _make_entry("hi1", tier="tier_2", risk="low"),
    ]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert results[0].success is True  # tier_1 + low risk → auto-applied
    assert results[1].success is False  # tier_1 + med risk → gated, user said no
    assert results[2].success is False  # tier_2 + low risk → gated, user said no


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_get_applier_raises_on_none_upgrade_type() -> None:
    with pytest.raises(ValueError, match="No applier registered"):
        _get_applier("none")  # type: ignore[arg-type]


def test_get_applier_returns_gepa_applier_for_gepa_target() -> None:
    from discord.hermes_upgrade.appliers.gepa_applier import GepaApplier

    applier = _get_applier("gepa_target")  # type: ignore[arg-type]
    assert isinstance(applier, GepaApplier)


def test_get_applier_raises_on_truly_unknown_upgrade_type() -> None:
    with pytest.raises(ValueError, match="No applier registered"):
        _get_applier("brand_new_made_up_type")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# apply_many graceful-degrade on unknown / failing appliers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_many_continues_after_value_error_from_get_applier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown upgrade_type must not crash the batch; produces a no-applier-for-type result."""
    good = MockApplier()

    def fake_get_applier(upgrade_type: str):
        if upgrade_type == "skill":
            return good
        raise ValueError(f"No applier registered for upgrade_type={upgrade_type}")

    monkeypatch.setattr(applier_module, "_get_applier", fake_get_applier)

    entries = [
        _make_entry("good1", upgrade_type="skill"),
        _make_entry("bad1", upgrade_type="gepa_target"),  # will hit ValueError branch
        _make_entry("good2", upgrade_type="skill"),
    ]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert len(results) == 3
    assert results[0].success is True and results[0].bookmark_id == "good1"
    assert results[1].success is False and results[1].bookmark_id == "bad1"
    assert "no-applier-for-type" in (results[1].notes or "")
    assert results[2].success is True and results[2].bookmark_id == "good2"


@pytest.mark.asyncio
async def test_apply_many_continues_after_generic_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-ValueError exception from apply_one becomes a failed-ApplyResult, not a crash."""

    class BlowupApplier(MockApplier):
        async def apply(self, entry: BacklogEntry) -> ApplyResult:  # type: ignore[override]
            raise RuntimeError("kaboom from applier")

    bomb = BlowupApplier()
    good = MockApplier()
    counter = {"n": 0}

    def fake_get_applier(_ut):
        counter["n"] += 1
        return bomb if counter["n"] == 1 else good

    monkeypatch.setattr(applier_module, "_get_applier", fake_get_applier)

    entries = [_make_entry("a"), _make_entry("b")]
    backlog_path = tmp_path / "backlog.jsonl"
    applied_log = tmp_path / "applied.jsonl"

    results = await apply_many(
        entries,
        backlog_path=backlog_path,
        applied_log_path=applied_log,
        auto_approve_low_risk=True,
    )

    assert len(results) == 2
    assert results[0].success is False
    assert "apply_one raised" in (results[0].notes or "")
    assert "RuntimeError" in (results[0].error or "")
    assert "kaboom" in (results[0].error or "")
    assert results[1].success is True


# ---------------------------------------------------------------------------
# BacklogEntry.applicable_or_pending helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        ("pending", True),
        ("failed", True),
        ("applied", False),
        ("skipped", False),
        ("rolled_back", False),
    ],
)
def test_applicable_or_pending(status: str, expected: bool) -> None:
    entry = _make_entry(apply_status=status)
    assert entry.applicable_or_pending() is expected
