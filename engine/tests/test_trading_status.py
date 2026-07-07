"""Phase 1c — trading-status reconciliation coverage (pure, offline).

Drives ``services.trading_status`` with injected sources. Covers the single-truth
derivation (``tradeable``), every split-brain disagreement rule, the intentional
non-disagreement (enabled + INSUFFICIENT_SAMPLE), verdict-age parsing, and the
roll-up. No files, DB, or engine — the whole point is that the reconciliation
logic is verifiable in isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.trading_status import (
    build_symbol_status,
    build_trading_status,
    summarize,
)

NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


def _v(verdict=None, family="trend", created_at=None, oos_trades=None):
    return {
        "verdict": verdict,
        "family": family,
        "created_at": created_at,
        "oos_trades": oos_trades,
    }


# ── single-truth: tradeable ────────────────────────────────────────────────


def test_enabled_authorized_pass_is_tradeable_and_agrees():
    s = build_symbol_status("MGC", enabled=True, authorized=True, verdict_row=_v("PASS"))
    assert s.tradeable is True
    assert s.config_agrees is True
    assert s.disagreements == []


def test_pass_but_disabled_is_not_tradeable():
    s = build_symbol_status("MGC", enabled=False, authorized=True, verdict_row=_v("PASS"))
    assert s.tradeable is False


def test_enabled_authorized_but_no_pass_not_tradeable():
    s = build_symbol_status("MES", enabled=True, authorized=True, verdict_row=_v("INSUFFICIENT_SAMPLE"))
    assert s.tradeable is False


def test_verdict_match_is_case_insensitive():
    s = build_symbol_status("MGC", enabled=True, authorized=True, verdict_row=_v("pass"))
    assert s.tradeable is True


# ── disagreement rules ─────────────────────────────────────────────────────


def test_disagreement_enabled_but_blocklisted():
    s = build_symbol_status("MNQ", enabled=True, authorized=False, verdict_row=_v("FAIL"))
    assert s.config_agrees is False
    assert any("DO_NOT_TRADE_SYMBOLS" in d for d in s.disagreements)


def test_disagreement_enabled_but_verdict_fail():
    s = build_symbol_status("MNQ", enabled=True, authorized=True, verdict_row=_v("FAIL"))
    assert s.config_agrees is False
    assert any("verdict is FAIL" in d for d in s.disagreements)


def test_disagreement_enabled_but_no_verdict():
    s = build_symbol_status("XYZ", enabled=True, authorized=True, verdict_row=None)
    assert s.config_agrees is False
    assert any("no gate-v2 verdict" in d for d in s.disagreements)


def test_disagreement_pass_authorized_but_disabled():
    # A validated, authorized edge left switched off (stale disable / missed).
    s = build_symbol_status("MGC", enabled=False, authorized=True, verdict_row=_v("PASS"))
    assert s.config_agrees is False
    assert any("disabled in paper_config" in d for d in s.disagreements)


# ── intentional NON-disagreements ──────────────────────────────────────────


def test_enabled_insufficient_sample_is_not_a_disagreement():
    # MES trend: enabled + gate withholding for more OOS data is EXPECTED.
    s = build_symbol_status("MES", enabled=True, authorized=True, verdict_row=_v("INSUFFICIENT_SAMPLE"))
    assert s.config_agrees is True
    assert s.disagreements == []
    assert s.tradeable is False


def test_disabled_blocklisted_failed_symbol_agrees():
    # MCL-like: correctly off everywhere.
    s = build_symbol_status("MCL", enabled=False, authorized=False, verdict_row=_v("FAIL"))
    assert s.config_agrees is True
    assert s.tradeable is False


def test_offmarket_symbol_only_blocklisted_agrees():
    # M2K: not in paper_config (enabled False) + blocklisted — consistently off.
    s = build_symbol_status("M2K", enabled=False, authorized=False, verdict_row=None)
    assert s.config_agrees is True
    assert s.tradeable is False


# ── verdict age parsing ────────────────────────────────────────────────────


def test_verdict_age_days_computed():
    s = build_symbol_status(
        "MGC", enabled=True, authorized=True,
        verdict_row=_v("PASS", created_at="2026-06-01T00:00:00+00:00"), now=NOW,
    )
    assert s.verdict_age_days == 10.0


def test_verdict_age_days_handles_z_suffix_and_naive():
    s = build_symbol_status(
        "MGC", enabled=True, authorized=True,
        verdict_row=_v("PASS", created_at="2026-06-09T00:00:00Z"), now=NOW,
    )
    assert s.verdict_age_days == 2.0


def test_verdict_age_none_when_unparseable_or_no_clock():
    bad = build_symbol_status("MGC", enabled=True, authorized=True,
                              verdict_row=_v("PASS", created_at="not-a-date"), now=NOW)
    assert bad.verdict_age_days is None
    no_clock = build_symbol_status("MGC", enabled=True, authorized=True,
                                   verdict_row=_v("PASS", created_at="2026-06-01T00:00:00+00:00"))
    assert no_clock.verdict_age_days is None


# ── build_trading_status + summarize ───────────────────────────────────────


def test_build_trading_status_composes_sorts_and_dedups():
    enabled = {"MGC": True, "MES": True, "MNQ": False, "MCL": False}
    verdicts = {"MGC": _v("PASS"), "MES": _v("INSUFFICIENT_SAMPLE"), "MNQ": _v("FAIL"), "MCL": _v("FAIL")}
    blocklist = {"MNQ", "MCL", "M2K"}
    statuses = build_trading_status(
        ["MGC", "MES", "MNQ", "MCL", "M2K", "MGC"],  # dup MGC
        enabled_for=lambda s: enabled.get(s, False),
        authorized_for=lambda s: s not in blocklist,
        verdict_for=lambda s: verdicts.get(s),
        now=NOW,
    )
    syms = [s.symbol for s in statuses]
    assert syms == sorted(set(syms))  # sorted, deduped
    assert "M2K" in syms and len(syms) == 5
    mgc = next(s for s in statuses if s.symbol == "MGC")
    assert mgc.tradeable is True


def test_summarize_counts():
    statuses = build_trading_status(
        ["MGC", "MES", "MNQ"],
        enabled_for=lambda s: s in {"MGC", "MES", "MNQ"},  # all enabled
        authorized_for=lambda s: s != "MNQ",               # MNQ blocklisted
        verdict_for=lambda s: {"MGC": _v("PASS"), "MES": _v("INSUFFICIENT_SAMPLE"), "MNQ": _v("FAIL")}[s],
        now=NOW,
    )
    summary = summarize(statuses)
    assert summary["total"] == 3
    assert summary["tradeable"] == 1            # only MGC
    assert summary["enabled"] == 3
    # counts SYMBOLS that disagree, not messages: MGC ok, MES insufficient is fine,
    # only MNQ disagrees (it trips two rules but is one symbol) -> 1.
    assert summary["disagreements"] == 1


def test_to_dict_is_json_friendly():
    s = build_symbol_status("MGC", enabled=True, authorized=True, verdict_row=_v("PASS"))
    d = s.to_dict()
    assert d["symbol"] == "MGC" and d["tradeable"] is True
    assert isinstance(d["disagreements"], list)
