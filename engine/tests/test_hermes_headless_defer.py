"""Regression: headless (no-TTY) Hermes apply runs DEFER — they must not
terminally skip.

Guards F3. Previously ``except EOFError: ans = "n"`` wrote the terminal
``skipped`` state for every non-auto-approvable entry on a scheduled/headless
run, permanently hiding it from a later interactive/authorized run
(``applicable_or_pending`` retries only ``pending``/``failed``). EOF (no TTY)
must instead leave the entry retryable, preserving the human-approval gate
without destroying the backlog.
"""

from __future__ import annotations

import builtins

from discord.hermes_upgrade import applier as A
from discord.hermes_upgrade.models import ApplyResult, BacklogEntry


class _StubApplier:
    async def dry_run(self, entry):
        return "stub diff"

    async def apply(self, entry):
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff="",
            post_apply_verification="ok",
            rollback_path="rb",
            notes="applied",
        )

    async def verify(self, entry, result):
        return True


def _entry(**over) -> BacklogEntry:
    base = {
        "bookmark_id": "bm1",
        "source_bookmark_url": "u",
        "source_discord_url": "u",
        "source_vault_path": "p",
        "upgrade_type": "skill",
        "title": "t",
        "rationale": "r",
        "implementation_steps": ["s"],
        "leverage_rank": 3,
        "risk": "med",  # NOT auto-approvable (needs tier_1 + low)
        "dependencies": [],
        "estimated_cost_usd": 0.0,
        "extracted_content": "c",
        "notes": "n",
        "tier": "tier_2",
    }
    base.update(over)
    return BacklogEntry(**base)


def _no_tty(monkeypatch):
    def _raise(*a, **k):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _raise)


async def test_apply_one_defers_when_no_tty(monkeypatch):
    monkeypatch.setattr(A, "_get_applier", lambda upgrade_type: _StubApplier())
    _no_tty(monkeypatch)
    res = await A.apply_one(_entry(), dry_run_only=False, auto_approve=False)
    assert res.deferred is True
    assert res.success is False
    assert "skipped" not in (res.notes or "").lower()


async def test_apply_many_leaves_deferred_entry_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_get_applier", lambda upgrade_type: _StubApplier())
    _no_tty(monkeypatch)
    entry = _entry()
    assert entry.apply_status == "pending"

    results = await A.apply_many(
        [entry],
        backlog_path=tmp_path / "backlog.jsonl",
        applied_log_path=tmp_path / "applied.jsonl",
    )

    assert results[0].deferred is True
    # The bug this guards: it used to become terminal "skipped".
    assert entry.apply_status == "pending"
    assert entry.applicable_or_pending() is True
    # A deferral is neither an apply nor a skip — it must not hit the applied-log.
    assert not (tmp_path / "applied.jsonl").exists()


async def test_explicit_user_n_still_terminally_skips(monkeypatch, tmp_path):
    """Interactive 'n' is unchanged: a real user skip is still terminal."""
    monkeypatch.setattr(A, "_get_applier", lambda upgrade_type: _StubApplier())
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "n")
    entry = _entry()
    await A.apply_many(
        [entry],
        backlog_path=tmp_path / "backlog.jsonl",
        applied_log_path=tmp_path / "applied.jsonl",
    )
    assert entry.apply_status == "skipped"
