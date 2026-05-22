"""Unit tests for engine.discord.hermes_upgrade.backlog."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from discord.hermes_upgrade.backlog import (
    assign_tier,
    default_backlog_dir,
    hydrate_entry,
    merge_with_existing,
    render_markdown,
    write_backlog,
)
from discord.hermes_upgrade.models import BacklogEntry, ClassifiedUpgrade

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_entry(
    bookmark_id: str = "bm1",
    *,
    tier: str = "tier_1",
    upgrade_type: str = "skill",
    title: str = "Install autonomous-ai-agents/claude-code",
    leverage_rank: int = 5,
    risk: str = "low",
    cost: float = 0.0,
    rationale: str = "High-signal community skill bundle.",
    steps: list[str] | None = None,
    deps: list[str] | None = None,
    extracted: str = "Battle-tested 30-skill bundle for Claude Code.",
    apply_status: str = "pending",
    apply_outcome: str = "",
    apply_timestamp: datetime | None = None,
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url=f"https://x.com/example/status/{bookmark_id}",
        source_discord_url=f"https://discord.com/channels/g/c/{bookmark_id}",
        source_vault_path=f"vault/bookmarks/{bookmark_id}.md",
        upgrade_type=upgrade_type,  # type: ignore[arg-type]
        title=title,
        rationale=rationale,
        implementation_steps=steps or ["hermes skill install <slug>"],
        leverage_rank=leverage_rank,
        risk=risk,  # type: ignore[arg-type]
        dependencies=deps or [],
        estimated_cost_usd=cost,
        extracted_content=extracted,
        notes="",
        tier=tier,  # type: ignore[arg-type]
        apply_status=apply_status,  # type: ignore[arg-type]
        apply_timestamp=apply_timestamp,
        apply_outcome=apply_outcome,
    )


def _mk_classified(
    bookmark_id: str,
    *,
    applicable: bool = True,
    leverage_rank: int = 4,
    risk: str = "low",
    upgrade_type: str = "skill",
    title: str = "T",
    rationale: str = "R",
) -> ClassifiedUpgrade:
    return ClassifiedUpgrade(
        bookmark_id=bookmark_id,
        applicable=applicable,
        upgrade_type=upgrade_type,  # type: ignore[arg-type]
        title=title,
        rationale=rationale,
        implementation_steps=["echo ok"],
        leverage_rank=leverage_rank,
        risk=risk,  # type: ignore[arg-type]
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content="snippet",
        notes="",
    )


# ---------------------------------------------------------------------------
# default_backlog_dir
# ---------------------------------------------------------------------------


def test_default_backlog_dir_is_absolute():
    p = default_backlog_dir()
    assert p.is_absolute()
    assert p.name == "upgrade"
    assert p.parent.name == ".hermes"


# ---------------------------------------------------------------------------
# assign_tier — covers all 4 outcomes
# ---------------------------------------------------------------------------


def test_assign_tier_defer_when_not_applicable():
    cu = _mk_classified("a", applicable=False, leverage_rank=5, risk="low")
    assert assign_tier(cu) == "defer"


def test_assign_tier_defer_when_leverage_one_even_if_applicable():
    cu = _mk_classified("a", applicable=True, leverage_rank=1, risk="low")
    assert assign_tier(cu) == "defer"


def test_assign_tier_tier_1_high_leverage_low_risk():
    # Requires a concrete target (e.g. github URL) to pass the concreteness gate
    cu = _mk_classified("a", applicable=True, leverage_rank=5, risk="low")
    cu.extracted_content = "https://github.com/mattamundson/repo"
    assert assign_tier(cu) == "tier_1"

    cu = _mk_classified("a", applicable=True, leverage_rank=4, risk="low")
    cu.extracted_content = "https://github.com/mattamundson/repo"
    assert assign_tier(cu) == "tier_1"


def test_assign_tier_tier_2_med_risk_or_lev_3():
    # leverage 3, low risk + concrete target
    cu = _mk_classified("a", applicable=True, leverage_rank=3, risk="low")
    cu.extracted_content = "https://github.com/mattamundson/repo"
    assert assign_tier(cu) == "tier_2"

    # leverage 4, med risk + concrete target
    cu = _mk_classified("a", applicable=True, leverage_rank=4, risk="med")
    cu.extracted_content = "https://github.com/mattamundson/repo"
    assert assign_tier(cu) == "tier_2"

    # community source demotion (tier_1 -> tier_2)
    cu = _mk_classified("a", applicable=True, leverage_rank=5, risk="low")
    cu.extracted_content = "https://github.com/untrusted/repo"
    assert assign_tier(cu) == "tier_2"


def test_assign_tier_tier_3_speculative():
    # leverage 2 — too low for tier_2 even with low risk
    cu = _mk_classified("a", applicable=True, leverage_rank=2, risk="low")
    assert assign_tier(cu) == "tier_3"
    # high risk falls to tier_3 regardless of leverage
    cu = _mk_classified("a", applicable=True, leverage_rank=5, risk="high")
    assert assign_tier(cu) == "tier_3"


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_includes_header_and_tally():
    entries = [
        _mk_entry("bm1", tier="tier_1", leverage_rank=5),
        _mk_entry("bm2", tier="tier_2", leverage_rank=3, risk="med"),
        _mk_entry("bm3", tier="defer", leverage_rank=1, risk="low"),
    ]
    md = render_markdown(entries, now=datetime(2026, 5, 20, 14, 30, tzinfo=timezone.utc))
    assert "# Hermes Upgrade Backlog — generated 2026-05-20 14:30 UTC" in md
    assert "Total candidates: 3" in md
    assert "tier_1: 1" in md
    assert "tier_2: 1" in md
    assert "tier_3: 0" in md
    assert "deferred: 1" in md


def test_render_markdown_has_all_tier_sections():
    md = render_markdown([_mk_entry("bm1", tier="tier_1")])
    assert "## Tier 1 — High leverage, low risk (do first)" in md
    assert "## Tier 2 — High leverage, medium risk" in md
    assert "## Tier 3 — Speculative" in md
    assert "## Deferred (0 items)" in md


def test_render_markdown_empty_tier_says_none():
    md = render_markdown([_mk_entry("bm1", tier="tier_1")])
    # tier_2 and tier_3 are empty → render _None._
    assert md.count("_None._") >= 2


def test_render_markdown_entry_fields():
    entry = _mk_entry(
        "bm42",
        tier="tier_1",
        title="Add MCP foo-server",
        upgrade_type="mcp_server",
        leverage_rank=5,
        risk="low",
        cost=0.0,
        rationale="Unblocks daily-readiness ingest.",
        steps=["hermes mcp add foo", "hermes config reload"],
        deps=["1Password api key"],
        extracted="MCP foo-server is the canonical bridge.",
    )
    md = render_markdown([entry])
    assert "### [bm42] Add MCP foo-server" in md
    assert "**Type:** mcp_server" in md
    assert "**Leverage:** 5/5" in md
    assert "**Risk:** low" in md
    assert "**Cost:** $0.00" in md
    assert "**Rationale:** Unblocks daily-readiness ingest." in md
    assert "1. `hermes mcp add foo`" in md
    assert "2. `hermes config reload`" in md
    assert "**Dependencies:** 1Password api key" in md
    assert "> MCP foo-server is the canonical bridge." in md
    assert "[bookmark](https://x.com/example/status/bm42)" in md


def test_render_markdown_apply_footer_present():
    md = render_markdown([_mk_entry("bm1")])
    assert "python -m discord.hermes_upgrade.applier --bookmark-id" in md
    assert "--tier tier_1 --auto-approve-low-risk" in md


def test_render_markdown_deferred_collapsed_to_one_line():
    deferred = _mk_entry(
        "bm9",
        tier="defer",
        title="Old library",
        rationale="Already installed",
    )
    md = render_markdown([deferred])
    assert "- `[bm9]` Old library — Already installed" in md
    # Deferred entries do NOT get full ### sections
    assert "### [bm9]" not in md


def test_render_markdown_sort_order_tier_then_leverage_desc():
    entries = [
        _mk_entry("low", tier="tier_1", leverage_rank=4),
        _mk_entry("high", tier="tier_1", leverage_rank=5),
        _mk_entry("t2", tier="tier_2", leverage_rank=3, risk="med"),
    ]
    md = render_markdown(entries)
    pos_high = md.index("[high]")
    pos_low = md.index("[low]")
    pos_t2 = md.index("[t2]")
    assert pos_high < pos_low < pos_t2


# ---------------------------------------------------------------------------
# write_backlog
# ---------------------------------------------------------------------------


def test_write_backlog_writes_both_files_and_creates_dir(tmp_path: Path):
    out = tmp_path / "nested" / "subdir"
    entries = [
        _mk_entry("bm1", tier="tier_1"),
        _mk_entry("bm2", tier="defer", leverage_rank=1),
    ]
    md_path, jsonl_path = write_backlog(entries, out_dir=out)

    assert md_path.exists()
    assert jsonl_path.exists()
    assert md_path.name == "backlog.md"
    assert jsonl_path.name == "backlog.jsonl"

    md = md_path.read_text(encoding="utf-8")
    assert "# Hermes Upgrade Backlog" in md

    jsonl_lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(jsonl_lines) == 2
    row1 = json.loads(jsonl_lines[0])
    assert row1["bookmark_id"] in {"bm1", "bm2"}
    assert "tier" in row1
    assert "apply_status" in row1


def test_write_backlog_jsonl_round_trips_through_model(tmp_path: Path):
    entry = _mk_entry(
        "bm1",
        tier="tier_1",
        apply_status="applied",
        apply_outcome="installed",
        apply_timestamp=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
    )
    _, jsonl_path = write_backlog([entry], out_dir=tmp_path)
    raw = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    revived = BacklogEntry.model_validate(raw)
    assert revived.bookmark_id == "bm1"
    assert revived.apply_status == "applied"
    assert revived.apply_outcome == "installed"
    assert revived.apply_timestamp is not None


# ---------------------------------------------------------------------------
# merge_with_existing
# ---------------------------------------------------------------------------


def test_merge_with_existing_no_prior_file_returns_input(tmp_path: Path):
    new = [_mk_entry("bm1")]
    out = merge_with_existing(new, tmp_path / "nope.jsonl")
    assert out == new


def test_merge_with_existing_preserves_apply_status_by_bookmark_id(tmp_path: Path):
    jsonl = tmp_path / "backlog.jsonl"
    prior = _mk_entry(
        "bm1",
        tier="tier_1",
        apply_status="applied",
        apply_outcome="hermes skill list shows the slug",
        apply_timestamp=datetime(2026, 5, 19, 9, 0, tzinfo=timezone.utc),
    )
    write_backlog([prior], out_dir=tmp_path)
    # The fresh classifier pass produces a "pending" entry for bm1
    fresh = _mk_entry("bm1", tier="tier_1", apply_status="pending")
    new_other = _mk_entry("bm2", tier="tier_2", apply_status="pending")
    merged = merge_with_existing([fresh, new_other], jsonl)

    by_id = {e.bookmark_id: e for e in merged}
    assert by_id["bm1"].apply_status == "applied"
    assert by_id["bm1"].apply_outcome == "hermes skill list shows the slug"
    assert by_id["bm1"].apply_timestamp is not None
    # Unknown bookmark_id remains pending
    assert by_id["bm2"].apply_status == "pending"


def test_merge_with_existing_skips_prior_pending(tmp_path: Path):
    """If the prior status was still 'pending', nothing is preserved."""
    jsonl = tmp_path / "backlog.jsonl"
    prior = _mk_entry("bm1", tier="tier_1", apply_status="pending")
    write_backlog([prior], out_dir=tmp_path)

    fresh = _mk_entry(
        "bm1",
        tier="tier_2",
        apply_status="pending",
        apply_outcome="brand new",
    )
    merged = merge_with_existing([fresh], jsonl)
    assert merged[0].tier == "tier_2"
    assert merged[0].apply_status == "pending"
    assert merged[0].apply_outcome == "brand new"


def test_merge_with_existing_drops_unknown_prior_ids(tmp_path: Path):
    """Prior bookmark_ids missing from the fresh batch are not resurrected."""
    jsonl = tmp_path / "backlog.jsonl"
    write_backlog(
        [_mk_entry("removed", tier="tier_1", apply_status="applied")],
        out_dir=tmp_path,
    )
    merged = merge_with_existing([_mk_entry("bm_new")], jsonl)
    assert len(merged) == 1
    assert merged[0].bookmark_id == "bm_new"


# ---------------------------------------------------------------------------
# hydrate_entry — sqlite join
# ---------------------------------------------------------------------------


@pytest.fixture
def hydrate_db(tmp_path: Path) -> Path:
    db = tmp_path / "hyd.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE discord_bookmarks (
            message_id        TEXT PRIMARY KEY NOT NULL,
            channel_id        TEXT,
            posted_at         TEXT NOT NULL,
            url               TEXT,
            domain            TEXT,
            source_type       TEXT,
            embed_title       TEXT,
            embed_description TEXT,
            imported_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            content           TEXT,
            author_id         TEXT,
            author_name       TEXT
        );
        CREATE TABLE discord_analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id     TEXT NOT NULL,
            artifact_type   TEXT NOT NULL,
            summary         TEXT NOT NULL,
            structured_json TEXT NOT NULL,
            vault_path      TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO discord_bookmarks (message_id, posted_at, url) VALUES (?, ?, ?)",
        ("bm_x", "2026-05-20T10:00:00Z", "https://x.com/foo/status/123"),
    )
    conn.execute(
        "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, "
        "structured_json, vault_path) VALUES (?, ?, ?, ?, ?)",
        ("bm_x", "url", "sum", "{}", "vault/x-bookmarks/bm_x.md"),
    )
    conn.commit()
    conn.close()
    return db


def test_hydrate_entry_pulls_url_and_vault_path(hydrate_db: Path):
    cu = _mk_classified("bm_x", upgrade_type="skill", title="Hello")
    entry = hydrate_entry(cu, hydrate_db, channel_id="ch1", guild_id="g1")
    assert entry.bookmark_id == "bm_x"
    assert entry.source_bookmark_url == "https://x.com/foo/status/123"
    assert entry.source_vault_path == "vault/x-bookmarks/bm_x.md"
    assert entry.source_discord_url == "https://discord.com/channels/g1/ch1/bm_x"
    # Tier is "defer" until caller overrides
    assert entry.tier == "defer"


def test_hydrate_entry_missing_row_degrades_gracefully(hydrate_db: Path):
    cu = _mk_classified("does_not_exist", upgrade_type="skill")
    entry = hydrate_entry(cu, hydrate_db, channel_id="ch1", guild_id="g1")
    assert entry.bookmark_id == "does_not_exist"
    assert entry.source_bookmark_url == ""
    assert entry.source_vault_path == ""
    # Discord URL is always constructed
    assert entry.source_discord_url == "https://discord.com/channels/g1/ch1/does_not_exist"
