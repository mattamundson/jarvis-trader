"""Tests for gate_v2_policy — advisory read-side for gate v2 verdicts.

Phase 3 LIGHT — read-only advisory module. Does NOT block trading routing;
only exposes `is_ungate_eligible()` and `get_last_verdict()` for dashboards,
cron logs, and future hard-enforcement Tier 3 work.

Staleness semantics: a verdict older than `max_age_days` is treated as
missing (`is_ungate_eligible → False`, `get_last_verdict → None`). This
closes the loophole where a stale PASS could masquerade as a current one.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest.gate_v2_policy import (
    MAX_VERDICT_AGE_DAYS,
    VerdictSnapshot,
    get_last_verdict,
    is_strategy_authorized,
    is_ungate_eligible,
    list_verdicts,
)

# ---------------------------------------------------------- #
# Fixtures                                                   #
# ---------------------------------------------------------- #


def _write_verdict(
    dir_: Path,
    *,
    symbol: str,
    family: str,
    rank: int,
    verdict: str,
    passed_via: str | None,
    created_at: str | None = None,
    age_days: float = 0.0,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    if created_at is None:
        ts = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
        created_at = ts.isoformat()
    doc = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if verdict == "PASS" and passed_via == "core" else "FAIL",
        "alt_verdict": "PASS" if verdict == "PASS" and passed_via == "alt" else "UNSCORED",
        "n_core_passed": 4 if passed_via == "core" else 2,
        "n_alt_passed": 5 if passed_via == "alt" else 0,
        "created_at": created_at,
        "aux_freshness": {"rolling_wfo": None, "fixed_params": None, "cost_sweep": None},
        "gate_v2": {},
    }
    path = dir_ / f"{symbol}_{family}_rank{rank}.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Monkeypatch GATE_V2_VERDICTS_DIR to a tmp path so tests don't collide."""
    from backtest import gate_v2_policy as policy

    monkeypatch.setattr(policy, "_default_verdicts_dir", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------- #
# get_last_verdict                                           #
# ---------------------------------------------------------- #


def test_get_last_verdict_returns_none_when_missing(tmp_verdicts_dir):
    assert get_last_verdict("MES") is None


def test_get_last_verdict_returns_most_recent(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
        age_days=1.0,
    )
    snap = get_last_verdict("MES")
    assert snap is not None
    assert snap.symbol == "MES"
    assert snap.verdict == "PASS"
    assert snap.passed_via == "alt"


def test_get_last_verdict_picks_newest_when_multiple(tmp_verdicts_dir):
    """Multiple rank verdicts → return newest by created_at."""
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=1,
        verdict="FAIL",
        passed_via=None,
        age_days=3.0,
    )
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
        age_days=0.5,
    )
    snap = get_last_verdict("MES")
    assert snap.rank == 7
    assert snap.verdict == "PASS"


def test_stale_verdict_treated_as_missing(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
        age_days=MAX_VERDICT_AGE_DAYS + 1,
    )
    assert get_last_verdict("MES") is None


# ---------------------------------------------------------- #
# is_ungate_eligible                                         #
# ---------------------------------------------------------- #


def test_is_ungate_eligible_requires_pass(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MCL",
        family="meanrev",
        rank=1,
        verdict="FAIL",
        passed_via=None,
    )
    assert is_ungate_eligible("MCL") is False


def test_is_ungate_eligible_pass_via_core(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=1,
        verdict="PASS",
        passed_via="core",
    )
    assert is_ungate_eligible("MES") is True


def test_is_ungate_eligible_pass_via_alt(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    assert is_ungate_eligible("MES") is True


def test_is_ungate_eligible_defaults_false_when_no_verdict(tmp_verdicts_dir):
    """Empty verdicts dir → default deny (never implicitly trust)."""
    assert is_ungate_eligible("MES") is False


def test_is_ungate_eligible_case_insensitive_symbol(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    # Symbol lookup should normalize case
    assert is_ungate_eligible("mes") is True
    assert is_ungate_eligible("Mes") is True


# ---------------------------------------------------------- #
# list_verdicts                                              #
# ---------------------------------------------------------- #


def test_list_verdicts_returns_all_fresh(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MCL",
        family="meanrev",
        rank=1,
        verdict="FAIL",
        passed_via=None,
    )
    results = list_verdicts()
    symbols = {v.symbol for v in results}
    assert symbols == {"MES", "MCL"}


def test_list_verdicts_excludes_stale(tmp_verdicts_dir):
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MCL",
        family="meanrev",
        rank=1,
        verdict="FAIL",
        passed_via=None,
        age_days=MAX_VERDICT_AGE_DAYS + 1,
    )
    results = list_verdicts()
    symbols = {v.symbol for v in results}
    assert symbols == {"MES"}  # stale MCL excluded


# ---------------------------------------------------------- #
# is_strategy_authorized                                     #
# ---------------------------------------------------------- #


_ENABLED_PAPER_CONFIGS = {
    # verdict_family/verdict_rank are REQUIRED by is_strategy_authorized (2026-07-21
    # refactor): authorization now matches the exact (symbol, family, rank) verdict
    # rather than any PASS on the symbol. Tests below write "trend" rank-1 verdicts.
    "XYZ": {"enabled": True, "symbol": "XYZ", "verdict_family": "trend", "verdict_rank": 1},
}

_DISABLED_PAPER_CONFIGS = {
    "XYZ": {"enabled": False, "symbol": "XYZ"},
}


def test_is_strategy_authorized_blocked_by_validation_only(tmp_verdicts_dir):
    """Symbol in VALIDATION_ONLY_INSTRUMENTS → not authorized regardless of paper_config."""
    from unittest.mock import patch

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset({"XYZ"})):
        with patch("backtest.paper_config.PAPER_CONFIGS", _ENABLED_PAPER_CONFIGS):
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "VALIDATION_ONLY_INSTRUMENTS" in reason


def test_is_strategy_authorized_blocked_by_missing_paper_config(tmp_verdicts_dir):
    """Symbol with no paper_config entry → not authorized."""
    from unittest.mock import patch

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", {}):
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "PAPER_CONFIGS" in reason


def test_is_strategy_authorized_blocked_by_disabled_paper_config(tmp_verdicts_dir):
    """Symbol with enabled=False in paper_config → not authorized."""
    from unittest.mock import patch

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", _DISABLED_PAPER_CONFIGS):
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "enabled=False" in reason


def test_is_strategy_authorized_blocked_by_missing_verdict(tmp_verdicts_dir):
    """Symbol with enabled=True but no gate v2 verdict → not authorized."""
    from unittest.mock import patch

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", _ENABLED_PAPER_CONFIGS):
            # No verdict written → is_verdict_authorized reports none on disk
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "no gate v2 verdict on disk" in reason


def test_is_strategy_authorized_authorized_when_all_conditions_met(tmp_verdicts_dir):
    """All three conditions met → authorized."""
    from unittest.mock import patch

    _write_verdict(
        tmp_verdicts_dir,
        symbol="XYZ",
        family="trend",
        rank=1,
        verdict="PASS",
        passed_via="core",
        age_days=0.5,
    )

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", _ENABLED_PAPER_CONFIGS):
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is True
    assert reason == "authorized"


def test_is_strategy_authorized_case_insensitive(tmp_verdicts_dir):
    """Symbol lookup normalises case end-to-end."""
    from unittest.mock import patch

    _write_verdict(
        tmp_verdicts_dir,
        symbol="XYZ",
        family="trend",
        rank=1,
        verdict="PASS",
        passed_via="core",
        age_days=0.5,
    )
    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", _ENABLED_PAPER_CONFIGS):
            authorized, _ = is_strategy_authorized("xyz")

    assert authorized is True


def test_is_strategy_authorized_stale_verdict_not_authorized(tmp_verdicts_dir):
    """Stale gate v2 PASS → not authorized (prevents indefinite authorization)."""
    from unittest.mock import patch

    _write_verdict(
        tmp_verdicts_dir,
        symbol="XYZ",
        family="trend",
        rank=1,
        verdict="PASS",
        passed_via="core",
        age_days=MAX_VERDICT_AGE_DAYS + 1,  # stale
    )

    with patch("agents.pipeline.VALIDATION_ONLY_INSTRUMENTS", frozenset()):
        with patch("backtest.paper_config.PAPER_CONFIGS", _ENABLED_PAPER_CONFIGS):
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "stale" in reason


# ---------------------------------------------------------- #
# VerdictSnapshot schema validation                          #
# ---------------------------------------------------------- #

_VALID_DOC = {
    "symbol": "MES",
    "family": "trend",
    "rank": 7,
    "verdict": "PASS",
    "passed_via": "alt",
    "core_verdict": "FAIL",
    "alt_verdict": "PASS",
    "n_core_passed": 2,
    "n_alt_passed": 5,
    "created_at": "2026-01-01T00:00:00+00:00",
    "aux_freshness": {},
    "gate_v2": {},
}


def test_verdict_snapshot_from_dict_valid():
    snap = VerdictSnapshot.from_dict(_VALID_DOC)
    assert snap.symbol == "MES"
    assert snap.verdict == "PASS"
    assert snap.passed_via == "alt"
    assert snap.rank == 7
    assert snap.gate_v2 == {}


def test_verdict_snapshot_rejects_invalid_verdict():
    bad = {**_VALID_DOC, "verdict": "MAYBE"}
    with pytest.raises(ValueError, match="verdict="):
        VerdictSnapshot.from_dict(bad)


def test_verdict_snapshot_rejects_invalid_passed_via():
    bad = {**_VALID_DOC, "passed_via": "unknown_path"}
    with pytest.raises(ValueError, match="passed_via="):
        VerdictSnapshot.from_dict(bad)


def test_verdict_snapshot_rejects_missing_required_field():
    bad = {k: v for k, v in _VALID_DOC.items() if k != "symbol"}
    with pytest.raises(ValueError, match="Missing required verdict field"):
        VerdictSnapshot.from_dict(bad)


def test_verdict_snapshot_rejects_invalid_created_at():
    bad = {**_VALID_DOC, "created_at": "not-a-date"}
    with pytest.raises(ValueError, match="created_at="):
        VerdictSnapshot.from_dict(bad)


def test_verdict_snapshot_equality():
    snap1 = VerdictSnapshot.from_dict(_VALID_DOC)
    snap2 = VerdictSnapshot.from_dict(_VALID_DOC)
    assert snap1 == snap2


def test_iter_verdict_files_skips_corrupt_file(tmp_verdicts_dir):
    """A verdict file with an invalid enum value is skipped; valid files still load."""
    # Write a valid verdict
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    # Write a corrupt verdict (invalid verdict value)
    corrupt = tmp_verdicts_dir / "MES_trend_rank99.json"
    corrupt.write_text(
        '{"symbol":"MES","family":"trend","rank":99,"verdict":"CORRUPTED","passed_via":null,"created_at":"2026-01-01T00:00:00+00:00"}'
    )

    results = list_verdicts(tmp_verdicts_dir)
    # Only the valid file loads; corrupt one is silently skipped
    assert len(results) == 1
    assert results[0].rank == 7


def test_iter_verdict_files_skips_rankless_without_warning(tmp_verdicts_dir, caplog):
    """Rankless verdicts (rank=null or missing) are skipped QUIETLY, not per-scan WARNINGs.

    Regression guard for the event-loop-churning log spam (2026-07): diversifier-family
    and pre-regate-backup verdicts carry no rank, so the loader raised int(None)/KeyError
    and re-logged a WARNING on every scan.  A rankless verdict can never satisfy a
    (symbol, family, rank) lookup, so it must be skipped without noise or affecting
    authorization of the valid verdicts around it.
    """
    from backtest.gate_v2_policy import _iter_verdict_files

    # A valid verdict that must still load normally
    _write_verdict(
        tmp_verdicts_dir,
        symbol="MES",
        family="trend",
        rank=7,
        verdict="PASS",
        passed_via="alt",
    )
    # rank explicitly null (diversifier-style)
    (tmp_verdicts_dir / "ZN_trend_diversifier.json").write_text(
        '{"symbol":"ZN","family":"trend","rank":null,"verdict":"INSUFFICIENT_SAMPLE",'
        '"passed_via":null,"created_at":"2026-07-01T00:00:00+00:00"}'
    )
    # rank key entirely absent
    (tmp_verdicts_dir / "M2K_orb_rank1.json").write_text(
        '{"symbol":"M2K","family":"orb","verdict":"FAIL",'
        '"passed_via":null,"created_at":"2026-07-01T00:00:00+00:00"}'
    )

    with caplog.at_level("WARNING", logger="jarvis_trader.gate_v2_policy"):
        loaded = list(_iter_verdict_files(tmp_verdicts_dir))

    # Only the ranked verdict is yielded; both rankless files skipped
    assert len(loaded) == 1
    assert loaded[0].symbol == "MES" and loaded[0].rank == 7
    # No "unreadable verdict" WARNING for the rankless files (the whole point of the fix)
    unreadable_warnings = [
        r for r in caplog.records if "unreadable verdict" in r.getMessage()
    ]
    assert unreadable_warnings == []


def test_iter_verdict_files_still_warns_on_genuine_corruption(tmp_verdicts_dir, caplog):
    """The rankless-skip fix must NOT silence genuinely malformed (invalid-enum) verdicts."""
    from backtest.gate_v2_policy import _iter_verdict_files

    # Ranked but with an invalid verdict enum → real corruption, must still WARN
    (tmp_verdicts_dir / "MES_trend_rank99.json").write_text(
        '{"symbol":"MES","family":"trend","rank":99,"verdict":"CORRUPTED",'
        '"passed_via":null,"created_at":"2026-01-01T00:00:00+00:00"}'
    )

    with caplog.at_level("WARNING", logger="jarvis_trader.gate_v2_policy"):
        loaded = list(_iter_verdict_files(tmp_verdicts_dir))

    assert loaded == []
    unreadable_warnings = [
        r for r in caplog.records if "unreadable verdict" in r.getMessage()
    ]
    assert len(unreadable_warnings) == 1
