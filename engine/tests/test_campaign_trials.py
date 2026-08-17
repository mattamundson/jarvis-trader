"""Tests for campaign-level DSR trial accounting (2026-08-17 audit follow-up)."""
from __future__ import annotations

import csv
import json

import pytest

from backtest.campaign_trials import (
    DIAGNOSTIC_TRIAL_COUNTS,
    count_journaled_trials,
    dsr_campaign_diagnostic,
)


def _write_journal(tmp_path, rows):
    p = tmp_path / "_journal.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "family", "verdict"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return p


class TestCountJournaledTrials:
    def test_counts_rows_for_symbol(self, tmp_path):
        p = _write_journal(tmp_path, [
            {"symbol": "MES", "family": "trend_rank11", "verdict": "PASS"},
            {"symbol": "MES", "family": "donchian_rank1", "verdict": "FAIL"},
            {"symbol": "MGC", "family": "trend_rank4", "verdict": "FAIL"},
        ])
        assert count_journaled_trials("MES", journal_path=p) == 2
        assert count_journaled_trials("MGC", journal_path=p) == 1

    def test_family_prefix_filter(self, tmp_path):
        p = _write_journal(tmp_path, [
            {"symbol": "MES", "family": "trend_rank11", "verdict": "PASS"},
            {"symbol": "MES", "family": "trend_rv_filter", "verdict": "FAIL"},
            {"symbol": "MES", "family": "donchian_rank1", "verdict": "FAIL"},
        ])
        assert count_journaled_trials("MES", family_prefix="trend", journal_path=p) == 2

    def test_case_insensitive_symbol(self, tmp_path):
        p = _write_journal(tmp_path, [{"symbol": "mes", "family": "trend", "verdict": "PASS"}])
        assert count_journaled_trials("MES", journal_path=p) == 1

    def test_missing_journal_returns_zero_not_raise(self, tmp_path):
        assert count_journaled_trials("MES", journal_path=tmp_path / "nope.csv") == 0


class TestDsrCampaignDiagnostic:
    def test_insufficient_trades_is_graceful(self):
        d = dsr_campaign_diagnostic([1.0, -1.0], initial_capital=50_000.0,
                                    n_trials_used_by_gate=3)
        assert d["sweep"] == {}
        assert "insufficient" in d["note"].lower()

    def test_dsr_is_monotonically_non_increasing_in_trials(self):
        """More trials tried => more selection bias => DSR must not increase."""
        rng_pnls = [300.0, -120.0, 450.0, -200.0, 180.0, -90.0, 520.0, -260.0] * 12
        d = dsr_campaign_diagnostic(rng_pnls, initial_capital=50_000.0,
                                    n_trials_used_by_gate=3, n_permutations=400)
        counts = sorted(int(k) for k in d["sweep"])
        vals = [d["sweep"][str(c)] for c in counts]
        for earlier, later in zip(vals, vals[1:], strict=True):
            assert later <= earlier + 1e-9, f"DSR rose with more trials: {vals}"

    def test_reports_gate_trial_count_and_breakpoints(self):
        pnls = [300.0, -120.0, 450.0, -200.0, 180.0, -90.0, 520.0, -260.0] * 12
        d = dsr_campaign_diagnostic(pnls, initial_capital=50_000.0,
                                    n_trials_used_by_gate=3, n_permutations=400)
        assert d["n_trials_used_by_gate"] == 3
        assert set(d["sweep"]) == {str(c) for c in DIAGNOSTIC_TRIAL_COUNTS}
        # breakpoints are either None (never fails in range) or a tested count
        for key in ("core_fails_at_or_above_trials", "alt_fails_at_or_above_trials"):
            assert d[key] is None or d[key] in DIAGNOSTIC_TRIAL_COUNTS

    def test_diagnostic_is_json_serializable(self):
        """It gets embedded in verdict JSON, so it must serialize cleanly."""
        pnls = [100.0, -50.0, 200.0, -80.0] * 10
        d = dsr_campaign_diagnostic(pnls, initial_capital=50_000.0,
                                    n_trials_used_by_gate=3, n_permutations=200)
        json.loads(json.dumps(d))

    def test_note_marks_it_non_authoritative(self):
        """Guard against a future caller wiring this into a verdict decision."""
        pnls = [100.0, -50.0, 200.0, -80.0] * 10
        d = dsr_campaign_diagnostic(pnls, initial_capital=50_000.0,
                                    n_trials_used_by_gate=3, n_permutations=200)
        assert "DIAGNOSTIC ONLY" in d["note"]
