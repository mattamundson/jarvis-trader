"""Tests for `experiments.feedback_aggregator`.

Uses a freshly-created SQLite file per test (via `tmp_path`) so rows
seeded in one case don't leak into another. The table DDL mirrors the
production schema v22 but only includes columns the aggregator reads.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from experiments import feedback_aggregator


def _create_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE mes_session_hypothesis (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry_hypothesis_side TEXT,
                entry_hypothesis_reason TEXT,
                open_price REAL,
                close_price REAL,
                outcome_delta REAL,
                outcome_recorded_at TEXT,
                UNIQUE(date, symbol)
            )
            """
        )
        conn.commit()


def _insert(
    db_path: str,
    *,
    day: date,
    side: str,
    delta: float | None,
    outcome_recorded_at: str | None = "2026-04-21T20:15:00+00:00",
    symbol: str = "MES",
    open_price: float = 5000.0,
    close_price: float | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mes_session_hypothesis
                (date, symbol, entry_hypothesis_side, entry_hypothesis_reason,
                 open_price, close_price, outcome_delta, outcome_recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (day.isoformat(), symbol, side, "test", open_price, close_price,
             delta, outcome_recorded_at),
        )
        conn.commit()


def test_missing_table_returns_none_without_raising(tmp_path):
    db = str(tmp_path / "empty.db")
    # Create file but NOT the table
    sqlite3.connect(db).close()
    rate, n = feedback_aggregator.get_recent_hit_rate(db_path=db)
    assert rate is None
    assert n == 0
    assert feedback_aggregator.get_last_session_hypothesis(db_path=db) is None


def test_empty_table_returns_none(tmp_path):
    db = str(tmp_path / "e.db")
    _create_table(db)
    rate, n = feedback_aggregator.get_recent_hit_rate(db_path=db)
    assert rate is None
    assert n == 0


def test_single_hit_returns_1_0(tmp_path):
    db = str(tmp_path / "h.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 21), side="long", delta=5.25)
    rate, n = feedback_aggregator.get_recent_hit_rate(
        db_path=db, today=date(2026, 4, 21)
    )
    assert rate == 1.0
    assert n == 1


def test_single_miss_returns_0_0_not_none(tmp_path):
    """Discriminates 'one losing bet' from 'no data' — real 0.0 is meaningful."""
    db = str(tmp_path / "m.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 21), side="long", delta=-3.0)
    rate, n = feedback_aggregator.get_recent_hit_rate(
        db_path=db, today=date(2026, 4, 21)
    )
    assert rate == 0.0
    assert n == 1


def test_mixed_hits_and_misses(tmp_path):
    db = str(tmp_path / "mix.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 17), side="long", delta=2.0)
    _insert(db, day=date(2026, 4, 18), side="short", delta=-1.0)
    _insert(db, day=date(2026, 4, 19), side="long", delta=4.5)
    _insert(db, day=date(2026, 4, 20), side="short", delta=3.0)
    rate, n = feedback_aggregator.get_recent_hit_rate(
        db_path=db, today=date(2026, 4, 20)
    )
    assert n == 4
    assert rate == pytest.approx(0.75)


def test_skip_hypotheses_excluded_from_rate(tmp_path):
    """A 'skip' means we took no position — it should not count as hit or miss."""
    db = str(tmp_path / "skip.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 18), side="skip", delta=0.0)
    _insert(db, day=date(2026, 4, 19), side="skip", delta=0.0)
    _insert(db, day=date(2026, 4, 20), side="long", delta=5.0)
    rate, n = feedback_aggregator.get_recent_hit_rate(
        db_path=db, today=date(2026, 4, 20)
    )
    assert n == 1
    assert rate == 1.0


def test_pending_rows_excluded(tmp_path):
    """Rows without outcome_recorded_at are pending; they must not affect hit rate."""
    db = str(tmp_path / "p.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 20), side="long", delta=5.0)
    _insert(
        db,
        day=date(2026, 4, 21),
        side="long",
        delta=None,
        outcome_recorded_at=None,
    )
    rate, n = feedback_aggregator.get_recent_hit_rate(
        db_path=db, today=date(2026, 4, 21)
    )
    assert n == 1
    assert rate == 1.0


# ─── Pipeline injection (roadmap P0.5) ──────────────────────────────────────


class TestPipelineForwardRecorderInjection:
    """TradingPipeline._inject_forward_recorder must be MES-only and observational.

    The key-injection (not consumption) is what matters — Bull/Bear/Trader
    prompts serialize `analyst_reports` as JSON, so adding the key makes the
    metric prompt-visible to the LLMs without any prompt rewrite.
    """

    def _make_pipeline(self):
        from agents.pipeline import TradingPipeline
        return TradingPipeline({}, None)

    def test_mes_symbol_injects_all_four_keys(self, monkeypatch):
        tp = self._make_pipeline()
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_recent_hit_rate",
            lambda **kwargs: (0.7, 10),
        )
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_last_session_hypothesis",
            lambda db_path=None: {"date": "2026-04-21", "side": "long"},
        )
        reports: dict = {}
        tp._inject_forward_recorder("MES", reports)
        m = reports["forward_recorder_metric"]
        assert m["hit_rate"] == 0.7
        assert m["samples"] == 10
        assert m["degraded"] is False
        assert m["last_hypothesis"]["date"] == "2026-04-21"

    def test_mes_degraded_flag_flips_below_5_samples(self, monkeypatch):
        tp = self._make_pipeline()
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_recent_hit_rate",
            lambda **kwargs: (0.5, 3),
        )
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_last_session_hypothesis",
            lambda db_path=None: None,
        )
        reports: dict = {}
        tp._inject_forward_recorder("MES", reports)
        assert reports["forward_recorder_metric"]["degraded"] is True

    def test_non_mes_symbol_is_noop(self):
        """MCL/MNQ must not receive the MES-specific forward-recorder key."""
        tp = self._make_pipeline()
        reports: dict = {"technical": {"signal": "LONG"}}
        tp._inject_forward_recorder("MCL", reports)
        tp._inject_forward_recorder("MNQ", reports)
        tp._inject_forward_recorder("SPY", reports)
        assert "forward_recorder_metric" not in reports
        assert reports == {"technical": {"signal": "LONG"}}  # untouched

    def test_aggregator_exception_is_swallowed(self, monkeypatch):
        """Never block the pipeline on a forward-recorder failure."""
        tp = self._make_pipeline()

        def _raise(**_):
            raise RuntimeError("db file missing")

        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_recent_hit_rate", _raise,
        )
        reports: dict = {}
        tp._inject_forward_recorder("MES", reports)  # must not raise
        assert "forward_recorder_metric" not in reports

    def test_symbol_casing_is_normalized(self, monkeypatch):
        """Accept mes / Mes / MES equivalently — callers shouldn't have to normalize."""
        tp = self._make_pipeline()
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_recent_hit_rate",
            lambda **kwargs: (0.6, 8),
        )
        monkeypatch.setattr(
            "experiments.feedback_aggregator.get_last_session_hypothesis",
            lambda db_path=None: None,
        )
        for variant in ("mes", "Mes", "MES"):
            reports: dict = {}
            tp._inject_forward_recorder(variant, reports)
            assert "forward_recorder_metric" in reports, f"failed for {variant!r}"


def test_stale_rows_excluded_by_max_age_days(tmp_path):
    """Default 7-day window must drop older rows even when n=10 would include them."""
    db = str(tmp_path / "stale.db")
    _create_table(db)
    today = date(2026, 4, 21)
    # Stale — 10 days ago
    _insert(db, day=today - timedelta(days=10), side="long", delta=99.0)
    # Fresh — yesterday
    _insert(db, day=today - timedelta(days=1), side="long", delta=-5.0)
    rate, n = feedback_aggregator.get_recent_hit_rate(db_path=db, today=today)
    assert n == 1
    assert rate == 0.0


def test_n_limit_caps_sample_count(tmp_path):
    """When more than n fresh rows exist, only the most-recent n feed the rate."""
    db = str(tmp_path / "cap.db")
    _create_table(db)
    today = date(2026, 4, 21)
    # 4 misses (older: days 7..4 ago — inside the 7-day window boundary still),
    # 3 hits (newer: days 3..1 ago).  All 7 dates distinct so UNIQUE holds.
    for days_ago in (7, 6, 5, 4):
        _insert(db, day=today - timedelta(days=days_ago), side="long", delta=-1.0)
    for days_ago in (3, 2, 1):
        _insert(db, day=today - timedelta(days=days_ago), side="long", delta=2.0)
    # n=3 should pick the 3 most-recent rows, which are the 3 hits.
    rate, n = feedback_aggregator.get_recent_hit_rate(n=3, db_path=db, today=today)
    assert n == 3
    assert rate == 1.0


def test_partial_history_less_than_n(tmp_path):
    """< n rows available → compute over whatever exists, report true count."""
    db = str(tmp_path / "partial.db")
    _create_table(db)
    today = date(2026, 4, 21)
    _insert(db, day=today - timedelta(days=1), side="long", delta=2.0)
    _insert(db, day=today - timedelta(days=2), side="long", delta=-1.0)
    rate, n = feedback_aggregator.get_recent_hit_rate(n=10, db_path=db, today=today)
    assert n == 2
    assert rate == 0.5


def test_get_last_session_hypothesis_returns_most_recent(tmp_path):
    db = str(tmp_path / "last.db")
    _create_table(db)
    _insert(db, day=date(2026, 4, 20), side="skip", delta=0.0)
    _insert(db, day=date(2026, 4, 21), side="long", delta=None,
            outcome_recorded_at=None, open_price=6388.25)
    row = feedback_aggregator.get_last_session_hypothesis(db_path=db)
    assert row is not None
    assert row["date"] == "2026-04-21"
    assert row["entry_hypothesis_side"] == "long"
    assert row["open_price"] == 6388.25
    assert row["outcome_recorded_at"] is None


def test_get_last_session_hypothesis_none_on_empty_table(tmp_path):
    db = str(tmp_path / "noop.db")
    _create_table(db)
    assert feedback_aggregator.get_last_session_hypothesis(db_path=db) is None


def test_get_last_session_hypothesis_none_when_table_missing(tmp_path):
    db = str(tmp_path / "nt.db")
    sqlite3.connect(db).close()
    assert feedback_aggregator.get_last_session_hypothesis(db_path=db) is None
