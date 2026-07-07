"""Unit tests: BullResearcher / BearResearcher Discord-briefing evidence adjustment.

Roadmap Phase 4 Task D1. Tests cover:
- Missing/malformed briefing → silent no-op
- bias × conviction × role matrix → conviction boost/dampen/no-op as spec
- Conviction cap (1.0) and floor (0.0)
- Price-target clamping against ib_levels.ibu100 (bull) / ibd100 (bear)
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.bear_researcher import BearReport, BearResearcherAgent  # noqa: E402
from agents.bull_researcher import BullReport, BullResearcherAgent  # noqa: E402


def _make_bull_report(conviction=0.5, price_target=None):
    return BullReport(
        symbol="MCL",
        timestamp=datetime(2026, 4, 19, 21, 0),
        bull_thesis="test thesis",
        key_evidence=["initial"],
        price_target=price_target,
        time_horizon="swing",
        conviction=conviction,
        counterargument_response="",
    )


def _make_bear_report(conviction=0.5, downside_target=None):
    return BearReport(
        symbol="MCL",
        timestamp=datetime(2026, 4, 19, 21, 0),
        bear_thesis="test thesis",
        key_risks=["initial"],
        downside_target=downside_target,
        time_horizon="swing",
        conviction=conviction,
        counterargument_response="",
    )


def _briefing(bias="neutral", conv=0.0, ib_levels=None):
    return {
        "corey_bias": {"directional_bias": bias, "conviction": conv},
        "ib_levels": ib_levels,
    }


# ── Bull: silent no-op cases ─────────────────────────────────────────────────


def test_bull_no_briefing_key_noop():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(report, {})
    assert report.conviction == 0.5
    assert report.key_evidence == ["initial"]


def test_bull_briefing_is_not_dict_noop():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(report, {"discord_briefing": None})
    assert report.conviction == 0.5

    report2 = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(report2, {"discord_briefing": "not a dict"})
    assert report2.conviction == 0.5


def test_bull_missing_corey_bias_noop():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(report, {"discord_briefing": {}})
    assert report.conviction == 0.5


def test_bull_conviction_below_threshold_noop():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bullish", conv=0.49)}
    )
    assert report.conviction == 0.5
    assert report.key_evidence == ["initial"]


def test_bull_neutral_bias_noop():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.9)}
    )
    assert report.conviction == 0.5


# ── Bull: conviction adjustments ─────────────────────────────────────────────


def test_bull_bullish_bias_above_threshold_boosts():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bullish", conv=0.8)}
    )
    assert report.conviction == pytest.approx(0.6)
    assert any("BULLISH" in ev for ev in report.key_evidence)


def test_bull_bearish_bias_above_threshold_dampens():
    report = _make_bull_report(conviction=0.5)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bearish", conv=0.7)}
    )
    assert report.conviction == pytest.approx(0.4)
    assert any("BEARISH" in ev for ev in report.key_evidence)


def test_bull_conviction_cap_at_one():
    report = _make_bull_report(conviction=0.95)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bullish", conv=1.0)}
    )
    assert report.conviction == pytest.approx(1.0)


def test_bull_conviction_floor_at_zero():
    report = _make_bull_report(conviction=0.05)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bearish", conv=1.0)}
    )
    assert report.conviction == pytest.approx(0.0)


def test_bull_handles_bad_conviction_type():
    report = _make_bull_report(conviction=0.5)
    briefing = {"corey_bias": {"directional_bias": "bullish", "conviction": "not a number"},
                "ib_levels": None}
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": briefing}
    )
    assert report.conviction == 0.5


# ── Bull: price-target clamp ─────────────────────────────────────────────────


def test_bull_price_target_above_ibu100_cleared():
    report = _make_bull_report(conviction=0.5, price_target=88.00)
    ib = {"ibu100": 85.50, "ib_high": 83.0, "ib_low": 81.0}
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=ib)}
    )
    assert report.price_target is None
    assert "ibu100" in report.counterargument_response


def test_bull_price_target_below_ibu100_kept():
    report = _make_bull_report(conviction=0.5, price_target=83.25)
    ib = {"ibu100": 85.50}
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=ib)}
    )
    assert report.price_target == 83.25


def test_bull_no_ib_levels_price_target_kept():
    report = _make_bull_report(conviction=0.5, price_target=100.0)
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=None)}
    )
    assert report.price_target == 100.0


def test_bull_no_price_target_no_adjustment():
    report = _make_bull_report(conviction=0.5, price_target=None)
    ib = {"ibu100": 85.50}
    BullResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=ib)}
    )
    assert report.price_target is None
    assert report.counterargument_response == ""


# ── Bear: silent no-op cases ─────────────────────────────────────────────────


def test_bear_no_briefing_key_noop():
    report = _make_bear_report(conviction=0.5)
    BearResearcherAgent._apply_discord_evidence(report, {})
    assert report.conviction == 0.5
    assert report.key_risks == ["initial"]


def test_bear_neutral_bias_noop():
    report = _make_bear_report(conviction=0.5)
    BearResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.9)}
    )
    assert report.conviction == 0.5


# ── Bear: conviction adjustments (symmetric) ─────────────────────────────────


def test_bear_bearish_bias_above_threshold_boosts():
    report = _make_bear_report(conviction=0.5)
    BearResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bearish", conv=0.8)}
    )
    assert report.conviction == pytest.approx(0.6)
    assert any("BEARISH" in r for r in report.key_risks)


def test_bear_bullish_bias_above_threshold_dampens():
    report = _make_bear_report(conviction=0.5)
    BearResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="bullish", conv=0.7)}
    )
    assert report.conviction == pytest.approx(0.4)
    assert any("BULLISH" in r for r in report.key_risks)


# ── Bear: downside-target clamp ──────────────────────────────────────────────


def test_bear_downside_target_below_ibd100_cleared():
    report = _make_bear_report(conviction=0.5, downside_target=78.00)
    ib = {"ibd100": 80.50, "ib_low": 81.0, "ib_high": 83.0}
    BearResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=ib)}
    )
    assert report.downside_target is None
    assert "ibd100" in report.counterargument_response


def test_bear_downside_target_above_ibd100_kept():
    report = _make_bear_report(conviction=0.5, downside_target=80.90)
    ib = {"ibd100": 80.50}
    BearResearcherAgent._apply_discord_evidence(
        report, {"discord_briefing": _briefing(bias="neutral", conv=0.0, ib_levels=ib)}
    )
    assert report.downside_target == 80.90


# ── Cross-check: same briefing, opposite role-reactions ──────────────────────


@pytest.mark.parametrize(
    "bias,expected_bull_delta,expected_bear_delta",
    [
        ("bullish", +0.1, -0.1),
        ("bearish", -0.1, +0.1),
        ("neutral", 0.0, 0.0),
    ],
)
def test_bull_bear_reactions_are_mirrored(bias, expected_bull_delta, expected_bear_delta):
    bull = _make_bull_report(conviction=0.5)
    bear = _make_bear_report(conviction=0.5)
    briefing = {"discord_briefing": _briefing(bias=bias, conv=0.9)}
    BullResearcherAgent._apply_discord_evidence(bull, briefing)
    BearResearcherAgent._apply_discord_evidence(bear, briefing)
    assert bull.conviction == pytest.approx(0.5 + expected_bull_delta)
    assert bear.conviction == pytest.approx(0.5 + expected_bear_delta)
