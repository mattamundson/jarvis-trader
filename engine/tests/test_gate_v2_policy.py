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
    "XYZ": {"enabled": True, "symbol": "XYZ"},
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
            # No verdict written → is_ungate_eligible returns False
            authorized, reason = is_strategy_authorized("XYZ")

    assert authorized is False
    assert "PASS verdict" in reason


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
    assert "PASS verdict" in reason
