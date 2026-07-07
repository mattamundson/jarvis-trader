"""
US-006 — DebateOrchestrator supplemental unit tests.

Existing debate test files (brier_debate_wiring, debate_corey_tiebreak,
sepa_debate_wiring) cover narrow integration scenarios. This file targets
the pure module-level helpers and the conviction-threshold scoring logic:
  - DebateResult.to_dict
  - _extract_case_text
  - _is_credit_error
  - _parse_evidence_fields
  - _apply_evidence_weight
  - DebateOrchestrator._build_initial_result
  - REGIME_DEBATE_THRESHOLDS table

Goal: raise debate.py coverage 32% → ≥50% with non-brittle behavioral tests.
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.bear_researcher import BearReport  # noqa: E402
from agents.bull_researcher import BullReport  # noqa: E402
from agents.debate import (  # noqa: E402
    _CREDIT_EXHAUSTED_SENTINEL,
    BRIER_BLEND_ALPHA,
    DEFAULT_DEBATE_THRESHOLD,
    REGIME_DEBATE_THRESHOLDS,
    DebateOrchestrator,
    DebateResult,
    _apply_evidence_weight,
    _extract_case_text,
    _is_credit_error,
    _parse_evidence_fields,
)

# ─────────────────────────────────────────────────────────────────────────────
# DebateResult.to_dict
# ─────────────────────────────────────────────────────────────────────────────


class TestDebateResultSerialization:
    def _result(self, **overrides) -> DebateResult:
        defaults = {"symbol": "MES", "timestamp": datetime(2026, 4, 24, 12, 0, 0)}
        defaults.update(overrides)
        return DebateResult(**defaults)

    def test_minimal_serialization_has_required_keys(self):
        d = self._result().to_dict()
        for key in (
            "symbol", "timestamp", "verdict", "debate_score",
            "rounds_completed", "credits_exhausted", "ic_avg", "ir_score",
        ):
            assert key in d

    def test_timestamp_is_iso_string(self):
        d = self._result().to_dict()
        # Must be parseable
        datetime.fromisoformat(d["timestamp"])

    def test_default_verdict_is_inconclusive(self):
        d = self._result().to_dict()
        assert d["verdict"] == "INCONCLUSIVE"

    def test_bull_report_serialized_when_present(self):
        bull = BullReport(
            symbol="MES",
            timestamp=datetime(2026, 4, 24, 12, 0, 0),
            bull_thesis="Strong uptrend",
            conviction=0.8,
        )
        d = self._result(bull_report=bull).to_dict()
        assert d["bull_report"] is not None
        assert d["bull_report"]["bull_thesis"] == "Strong uptrend"

    def test_null_reports_serialize_as_none(self):
        d = self._result().to_dict()
        assert d["bull_report"] is None
        assert d["bear_report"] is None
        assert d["tail_risk_report"] is None

    def test_sepa_fields_round_trip(self):
        d = self._result(sepa_score=0.72, sepa_nudge=0.05).to_dict()
        assert d["sepa_score"] == 0.72
        assert d["sepa_nudge"] == 0.05


# ─────────────────────────────────────────────────────────────────────────────
# _extract_case_text
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Stub:
    bull_thesis: str = ""
    bear_thesis: str = ""
    summary: str = ""
    thesis: str = ""
    reasoning: str = ""

    def to_dict(self):
        return {"bull_thesis": self.bull_thesis, "summary": self.summary}


class TestExtractCaseText:
    def test_none_report_returns_default_message(self):
        assert "No bull argument available" in _extract_case_text(None, "bull")
        assert "No bear argument available" in _extract_case_text(None, "bear")

    def test_uses_bull_thesis_first(self):
        s = _Stub(bull_thesis="bullish breakout above 5800")
        assert _extract_case_text(s, "bull") == "bullish breakout above 5800"

    def test_falls_back_to_summary_when_thesis_missing(self):
        s = _Stub(summary="Mixed signals overall")
        result = _extract_case_text(s, "bull")
        # summary is checked AFTER bull_thesis/bear_thesis, but is in the chain
        assert result == "Mixed signals overall"

    def test_to_dict_fallback_when_no_named_attrs(self):
        @dataclass
        class Other:
            note: str = "this is a long note value to pass the length filter"

            def to_dict(self):
                return {"note": self.note}

        result = _extract_case_text(Other(), "bull")
        assert "note" in result

    def test_str_fallback_when_to_dict_raises(self):
        class Bad:
            def to_dict(self):
                raise RuntimeError("no")

            def __str__(self):
                return "raw bad object"

        result = _extract_case_text(Bad(), "bull")
        assert "raw bad object" in result


# ─────────────────────────────────────────────────────────────────────────────
# _is_credit_error
# ─────────────────────────────────────────────────────────────────────────────


class TestIsCreditError:
    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("credit balance too low", True),
            ("Anthropic: insufficient credits to continue", True),
            ("your credit balance is depleted", True),
            ("Billing error: please add funds", True),
            ("payment required for premium tier", True),
            ("HTTP 402 - Payment Required", True),
            ("Connection refused", False),
            ("Rate limit hit (429)", False),
            ("internal server error 500", False),
        ],
    )
    def test_classification(self, msg, expected):
        assert _is_credit_error(Exception(msg)) is expected


# ─────────────────────────────────────────────────────────────────────────────
# _parse_evidence_fields
# ─────────────────────────────────────────────────────────────────────────────


class TestParseEvidenceFields:
    def test_full_metadata_parsed(self):
        text = "SCORE: 7/10 | EVIDENCE_COUNT: 4 | EVIDENCE_QUALITY: high"
        count, quality = _parse_evidence_fields(text)
        assert count == 4
        assert quality == "high"

    def test_count_only(self):
        count, quality = _parse_evidence_fields("EVIDENCE_COUNT: 2")
        assert count == 2
        assert quality is None

    def test_quality_only(self):
        count, quality = _parse_evidence_fields("EVIDENCE_QUALITY: medium")
        assert count is None
        assert quality == "medium"

    def test_empty_text_returns_none(self):
        count, quality = _parse_evidence_fields("")
        assert count is None
        assert quality is None

    def test_case_insensitive_quality(self):
        _, quality = _parse_evidence_fields("EVIDENCE_QUALITY: HIGH")
        assert quality == "high"

    def test_invalid_quality_value_ignored(self):
        _, quality = _parse_evidence_fields("EVIDENCE_QUALITY: terrible")
        assert quality is None


# ─────────────────────────────────────────────────────────────────────────────
# _apply_evidence_weight
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyEvidenceWeight:
    def test_no_metadata_returns_raw_score(self):
        assert _apply_evidence_weight(7, None, None) == 7.0

    def test_high_quality_amplifies(self):
        # raw=7, count=3, high → 7 × (1 + 0.3) × 1.1 = 10.01
        weighted = _apply_evidence_weight(7, 3, "high")
        assert weighted == pytest.approx(10.01, abs=0.001)

    def test_low_quality_reduces(self):
        # raw=7, count=3, low → 7 × 1.3 × 0.9 = 8.19
        weighted = _apply_evidence_weight(7, 3, "low")
        assert weighted == pytest.approx(8.19, abs=0.001)

    def test_count_capped_at_5(self):
        # raw=5, count=10 (clamped to 5) → 5 × (1 + 0.5) × 1.0 = 7.5
        weighted = _apply_evidence_weight(5, 10, "medium")
        assert weighted == pytest.approx(7.5, abs=0.001)

    def test_default_count_when_only_quality_present(self):
        # count=None → default 3, quality=high → 5 × (1 + 0.3) × 1.1 = 7.15
        weighted = _apply_evidence_weight(5, None, "high")
        assert weighted == pytest.approx(7.15, abs=0.001)


# ─────────────────────────────────────────────────────────────────────────────
# DebateOrchestrator._build_initial_result
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildInitialResult:
    @pytest.fixture
    def orch(self):
        return DebateOrchestrator()

    def _bull(self, conviction: float) -> BullReport:
        return BullReport(symbol="MES", timestamp=datetime.now(), conviction=conviction)

    def _bear(self, conviction: float) -> BearReport:
        return BearReport(symbol="MES", timestamp=datetime.now(), conviction=conviction)

    def test_strong_bull_combined_above_threshold(self, orch):
        # bull=0.8, bear=0.2 → combined=0.6 ≥ 0.15 → "Bull thesis stronger" + "long"
        result = orch._build_initial_result("MES", self._bull(0.8), self._bear(0.2))
        assert result.debate_summary == "Bull thesis stronger"
        assert result.recommended_direction == "long"
        assert result.combined_signal == 0.6

    def test_strong_bear_combined_below_neg_threshold(self, orch):
        result = orch._build_initial_result("MES", self._bull(0.2), self._bear(0.8))
        assert result.debate_summary == "Bear thesis stronger"
        assert result.recommended_direction == "short"
        assert result.combined_signal == -0.6

    def test_inconclusive_when_combined_within_threshold(self, orch):
        # bull=0.5 bear=0.5 → combined=0.0 → INCONCLUSIVE
        result = orch._build_initial_result("MES", self._bull(0.5), self._bear(0.5))
        assert result.debate_summary == "Inconclusive"
        assert result.recommended_direction == "flat"

    def test_summary_threshold_strict_above(self, orch):
        # bull=0.5 bear=0.36 → combined=0.14 < 0.15 → still Inconclusive
        result = orch._build_initial_result("MES", self._bull(0.5), self._bear(0.36))
        assert result.debate_summary == "Inconclusive"

    def test_direction_threshold_independent_of_summary(self, orch):
        # bull=0.5 bear=0.39 → combined=0.11 ≥ 0.10 (DIR threshold) but < 0.15 (CONV threshold)
        # → summary=Inconclusive, direction=long (the looser DIR threshold trips first)
        result = orch._build_initial_result("MES", self._bull(0.5), self._bear(0.39))
        assert result.debate_summary == "Inconclusive"
        assert result.recommended_direction == "long"

    def test_rounds_completed_is_one(self, orch):
        result = orch._build_initial_result("MES", self._bull(0.5), self._bear(0.5))
        assert result.rounds_completed == 1


# ─────────────────────────────────────────────────────────────────────────────
# Configuration constants
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigConstants:
    def test_regime_thresholds_have_all_expected_regimes(self):
        for regime in (
            "COMPRESSION", "TRENDING_BULL", "TRENDING_BEAR",
            "RANGE_BOUND", "EXHAUSTED", "RANGING", "CAUTION",
        ):
            assert regime in REGIME_DEBATE_THRESHOLDS

    def test_default_threshold_is_positive_under_one(self):
        assert 0 < DEFAULT_DEBATE_THRESHOLD < 1.0

    def test_brier_blend_alpha_in_zero_one(self):
        assert 0.0 <= BRIER_BLEND_ALPHA <= 1.0

    def test_compression_threshold_tightest(self):
        # COMPRESSION is highest-conviction regime, should have smallest threshold
        assert REGIME_DEBATE_THRESHOLDS["COMPRESSION"] <= REGIME_DEBATE_THRESHOLDS["RANGE_BOUND"]
        assert REGIME_DEBATE_THRESHOLDS["COMPRESSION"] <= REGIME_DEBATE_THRESHOLDS["EXHAUSTED"]

    def test_credit_exhausted_sentinel_is_string(self):
        assert isinstance(_CREDIT_EXHAUSTED_SENTINEL, str)
        assert "credit" in _CREDIT_EXHAUSTED_SENTINEL.lower() or "exhausted" in _CREDIT_EXHAUSTED_SENTINEL.lower()
