"""Unit tests for the incremental-scan cache in discord/hermes_upgrade/__main__.py.

Root cause under test: scanner.py has no date/already-seen filter, so every
run re-scores the channel's ENTIRE bookmark history. Before this fix, main()
also re-classified every one of those candidates via the LLM on every run,
which was the dominant driver of the Anthropic + Kimi credit burn (826 of
~1,278 calls on 2026-08-12 came from a single daily run of this job). These
tests pin that only new / previously-errored candidates reach classify_batch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from discord.hermes_upgrade import __main__ as cli
from discord.hermes_upgrade.backlog import write_backlog
from discord.hermes_upgrade.models import BacklogEntry, Candidate, ClassifiedUpgrade

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_entry(bookmark_id: str, *, title: str = "Real upgrade", tier: str = "tier_2") -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url=f"https://x.com/example/status/{bookmark_id}",
        source_discord_url=f"https://discord.com/channels/g/c/{bookmark_id}",
        source_vault_path="",
        upgrade_type="skill",
        title=title,
        rationale="r",
        implementation_steps=["hermes skill install foo"],
        leverage_rank=3,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content="",
        notes="",
        tier=tier,  # type: ignore[arg-type]
        apply_status="pending",
    )


def _mk_candidate(bookmark_id: str) -> Candidate:
    return Candidate(
        bookmark_id=bookmark_id,
        analysis_id=1,
        url="https://github.com/x/y",
        summary="s",
        structured_json="{}",
        topics=["agent"],
        has_action_item=True,
        source_kind="github",
        artifact_type="url",
        posted_at="2026-08-12T00:00:00Z",
        score=0.9,
    )


class _RecordingClassifier:
    """Stand-in for classify_batch — records what it was asked to classify."""

    def __init__(self) -> None:
        self.received_ids: list[str] = []

    async def __call__(self, candidates: list[Candidate], *, concurrency: int = 5) -> list[ClassifiedUpgrade]:
        self.received_ids = [c.bookmark_id for c in candidates]
        return [
            ClassifiedUpgrade(
                bookmark_id=c.bookmark_id,
                applicable=True,
                upgrade_type="skill",
                title=f"fresh-{c.bookmark_id}",
                rationale="freshly classified",
                implementation_steps=["hermes skill install bar"],
                leverage_rank=2,
                risk="low",
                dependencies=[],
                estimated_cost_usd=0.0,
                extracted_content="",
                notes="",
            )
            for c in candidates
        ]


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "hermes_upgrade_out"


@pytest.fixture
def scratch_db(tmp_path: Path) -> Path:
    # hydrate_entry() degrades gracefully (catches sqlite3.Error) when the
    # discord_bookmarks/discord_analyses tables are missing, so an empty
    # sqlite file is sufficient for these tests.
    db = tmp_path / "scratch.db"
    db.touch()
    return db


# ---------------------------------------------------------------------------
# Incremental split
# ---------------------------------------------------------------------------


def test_main_skips_llm_for_already_classified_candidates(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, scratch_db: Path
):
    """A bookmark_id with a real prior classification must NOT hit the LLM again."""
    out_dir.mkdir(parents=True)
    write_backlog([_mk_entry("bm-cached", title="Prior real result")], out_dir=out_dir)

    candidates = [_mk_candidate("bm-cached"), _mk_candidate("bm-new")]
    monkeypatch.setattr(cli, "scan_for_candidates", lambda *a, **k: candidates)
    recorder = _RecordingClassifier()
    monkeypatch.setattr(cli, "classify_batch", recorder)

    rc = cli.main(["--db", str(scratch_db), "--out-dir", str(out_dir)])

    assert rc == 0
    # Only the genuinely new candidate should have reached the classifier.
    assert recorder.received_ids == ["bm-new"]


def test_main_retries_prior_classifier_errors(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, scratch_db: Path
):
    """A prior '<classifier error>' placeholder is NOT a real result — must be retried."""
    out_dir.mkdir(parents=True)
    write_backlog(
        [_mk_entry("bm-errored", title="<classifier error>", tier="defer")],
        out_dir=out_dir,
    )

    candidates = [_mk_candidate("bm-errored")]
    monkeypatch.setattr(cli, "scan_for_candidates", lambda *a, **k: candidates)
    recorder = _RecordingClassifier()
    monkeypatch.setattr(cli, "classify_batch", recorder)

    rc = cli.main(["--db", str(scratch_db), "--out-dir", str(out_dir)])

    assert rc == 0
    assert recorder.received_ids == ["bm-errored"]


def test_main_force_reclassify_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, scratch_db: Path
):
    out_dir.mkdir(parents=True)
    write_backlog([_mk_entry("bm-cached")], out_dir=out_dir)

    candidates = [_mk_candidate("bm-cached")]
    monkeypatch.setattr(cli, "scan_for_candidates", lambda *a, **k: candidates)
    recorder = _RecordingClassifier()
    monkeypatch.setattr(cli, "classify_batch", recorder)

    rc = cli.main(
        ["--db", str(scratch_db), "--out-dir", str(out_dir), "--force-reclassify"]
    )

    assert rc == 0
    assert recorder.received_ids == ["bm-cached"]


def test_main_combines_cached_and_fresh_entries_in_output(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, scratch_db: Path
):
    """The written backlog must contain BOTH the reused cache hit and the fresh result."""
    out_dir.mkdir(parents=True)
    write_backlog([_mk_entry("bm-cached", title="Prior real result")], out_dir=out_dir)

    candidates = [_mk_candidate("bm-cached"), _mk_candidate("bm-new")]
    monkeypatch.setattr(cli, "scan_for_candidates", lambda *a, **k: candidates)
    monkeypatch.setattr(cli, "classify_batch", _RecordingClassifier())

    rc = cli.main(["--db", str(scratch_db), "--out-dir", str(out_dir)])
    assert rc == 0

    written = (out_dir / "backlog.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ids = set()
    for line in written:
        import json

        ids.add(json.loads(line)["bookmark_id"])
    assert ids == {"bm-cached", "bm-new"}


def test_main_no_prior_backlog_classifies_everything(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, scratch_db: Path
):
    """First-ever run (no backlog.jsonl yet) has nothing to cache against."""
    candidates = [_mk_candidate("bm-1"), _mk_candidate("bm-2")]
    monkeypatch.setattr(cli, "scan_for_candidates", lambda *a, **k: candidates)
    recorder = _RecordingClassifier()
    monkeypatch.setattr(cli, "classify_batch", recorder)

    rc = cli.main(["--db", str(scratch_db), "--out-dir", str(out_dir)])

    assert rc == 0
    assert sorted(recorder.received_ids) == ["bm-1", "bm-2"]
