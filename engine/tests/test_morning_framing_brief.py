"""
Unit tests for the automated morning framing brief (framing_context +
framing_synthesis + morning_framing_brief's chunker). All pure/fixture-based —
no network, no LLM call, no DB.
"""

from datetime import date

import pytest

from analysis.framing_context import is_bias_usable, resolve_confidence_tier
from analysis.framing_synthesis import (
    _SKILL_MD_PATH,
    build_prompt,
    build_system_prompt,
    parse_brief,
)
from discord.commentary_processor import CoreySessionBias
from scripts.morning_framing_brief import chunk_for_discord


def _bias(data_quality: str, message_count: int = 5, **overrides) -> CoreySessionBias:
    defaults = {
        "date": date(2026, 7, 8),
        "session_type": "trend_day",
        "directional_bias": "bearish",
        "key_levels": [7525.0, 29227.0],
        "ib_bias": "below_ib",
        "specific_triggers": ["ES fails 7525", "NQ fails 29227"],
        "conviction": 0.7,
        "corey_quote": "Confirmed downside expansion phase led by NQ.",
        "message_count": message_count,
        "data_quality": data_quality,
    }
    defaults.update(overrides)
    return CoreySessionBias(**defaults)


# ---------------------------------------------------------------------------
# is_bias_usable — the data_quality='none'-with-messages pitfall
# ---------------------------------------------------------------------------


class TestIsBiasUsable:
    def test_fresh_bias_is_usable(self):
        assert is_bias_usable(_bias("fresh")) is True

    def test_stale_bias_is_usable(self):
        assert is_bias_usable(_bias("stale")) is True

    def test_none_quality_is_not_usable(self):
        assert is_bias_usable(_bias("none")) is False

    def test_none_quality_with_messages_is_still_not_usable(self):
        """The specific pitfall: message_count > 0 with data_quality='none' means
        a prior LLM extraction failure, NOT a real neutral/bearish signal."""
        assert is_bias_usable(_bias("none", message_count=12)) is False

    def test_missing_bias_is_not_usable(self):
        assert is_bias_usable(None) is False


# ---------------------------------------------------------------------------
# resolve_confidence_tier — single source of truth for the label
# ---------------------------------------------------------------------------


class TestResolveConfidenceTier:
    def test_usable_corey_bias_is_highest(self):
        tier = resolve_confidence_tier(_bias("fresh"), {"MES": None, "MNQ": None})
        assert tier == "HIGHEST"

    def test_engine_levels_without_corey_is_high(self):
        tier = resolve_confidence_tier(_bias("none"), {"MES": object(), "MNQ": None})
        assert tier == "HIGH"

    def test_neither_source_is_low(self):
        tier = resolve_confidence_tier(_bias("none"), {"MES": None, "MNQ": None})
        assert tier == "LOW"

    def test_missing_corey_bias_falls_through_to_engine_levels(self):
        tier = resolve_confidence_tier(None, {"MES": object()})
        assert tier == "HIGH"


# ---------------------------------------------------------------------------
# framing_synthesis.build_system_prompt — the guard test for SKILL.md parsing
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_real_skill_md_parses_without_error(self):
        """Guard test: if SKILL.md is ever reformatted such that the Output
        template / Bias rules / Hard rules headers change, this fails loudly
        here instead of silently breaking the automated brief's prompt."""
        prompt = build_system_prompt(_SKILL_MD_PATH)
        assert "Output template" in prompt or "confidence" in prompt.lower()
        assert "Bias rules" in prompt
        assert "Hard rules" in prompt

    def test_real_skill_md_contains_required_output_headers(self):
        prompt = build_system_prompt(_SKILL_MD_PATH)
        for required in ("Level confidence:", "Structural Levels", "Scenario Map", "Caveats:"):
            assert required in prompt, f"missing {required!r} in extracted SKILL.md template"

    def test_missing_section_raises(self, tmp_path):
        bad_skill_md = tmp_path / "SKILL.md"
        bad_skill_md.write_text("# Some other section\ncontent only\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing expected section header"):
            build_system_prompt(bad_skill_md)


# ---------------------------------------------------------------------------
# framing_synthesis.build_prompt / parse_brief
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_embeds_context_as_json(self):
        context = {"target_date": "2026-07-08", "confidence_tier": "HIGH"}
        prompt = build_prompt(context)
        assert "2026-07-08" in prompt
        assert "HIGH" in prompt


_VALID_BRIEF = """\
Morning Framing — Wed, 2026-07-08
Level confidence: HIGH (engine IB feed)

Structural Levels
ES / NQ tables here

Scenario Map
Scenario 1, 2, 3

Caveats: pre-open forecast
"""


class TestParseBrief:
    def test_valid_brief_passes(self):
        assert parse_brief(_VALID_BRIEF) == _VALID_BRIEF.strip()

    def test_strips_markdown_code_fence(self):
        fenced = f"```markdown\n{_VALID_BRIEF}```"
        assert parse_brief(fenced).startswith("Morning Framing")

    def test_missing_required_header_raises(self):
        broken = _VALID_BRIEF.replace("Scenario Map", "Something Else")
        with pytest.raises(ValueError, match="missing required section"):
            parse_brief(broken)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty brief"):
            parse_brief("")


# ---------------------------------------------------------------------------
# morning_framing_brief.chunk_for_discord
# ---------------------------------------------------------------------------


class TestChunkForDiscord:
    def test_short_text_is_one_chunk(self):
        chunks = chunk_for_discord("short brief", limit=2000)
        assert chunks == ["short brief"]

    def test_splits_on_paragraph_boundaries_without_exceeding_limit(self):
        blocks = [f"Section {i}: " + ("x" * 500) for i in range(6)]
        text = "\n\n".join(blocks)
        chunks = chunk_for_discord(text, limit=2000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 2000
        # No content lost across the split.
        assert "".join(chunks).replace("\n\n", "") == "".join(blocks)

    def test_oversized_single_block_hard_splits(self):
        block = "y" * 5000
        chunks = chunk_for_discord(block, limit=2000)
        assert len(chunks) == 3
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks) == block
