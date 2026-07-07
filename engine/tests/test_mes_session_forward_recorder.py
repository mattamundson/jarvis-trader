"""Regression tests for the MES session hypothesis forward-recorder.

Covered:
  Recorder:
    - Fresh + directional + high-conviction → "long"/"short" hypothesis
    - Stale data_quality → "skip"
    - Low conviction → "skip"
    - Neutral directional → "skip"
    - Idempotent on UNIQUE(date, symbol)
    - Graceful when data_manager is None (no open_price)
    - Graceful when TV bridge returns unavailable snapshot
    - Writes gamma_snapshot_json and ib_levels_json as valid JSON
  Outcome:
    - Long delta = close - open
    - Short delta = open - close
    - Skip delta = 0.0
    - Missing bars → row stays pending (no partial update)
    - Missing open_price + long side → delta=None, still stamps outcome_recorded_at
    - Already-filled rows are not re-updated (idempotent)
    - for_date filter narrows to single row
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pytest

from database.migrations import run_migrations
from experiments.mes_session_outcome import (
    _compute_delta,
    _hlc_from_bars,
    fill_outcomes,
)
from experiments.mes_session_recorder import (
    _derive_hypothesis,
    _gamma_snapshot_to_dict,
    record_session,
)

# ── Test fixtures / fakes ────────────────────────────────────────────────────


@dataclass
class FakeCoreyBias:
    directional_bias: str = "bullish"
    conviction: float = 0.7
    session_type: str = "trend_day"
    ib_bias: str = "above_ib"
    data_quality: str = "fresh"


@dataclass
class FakeBriefing:
    corey_bias: FakeCoreyBias
    ib_levels: Optional[dict] = None


@dataclass
class FakeSnapshot:
    """Mirrors the subset of TVIndicatorSnapshot the recorder reads."""

    gex_flip: Optional[float] = 5800.0
    call_wall: Optional[float] = 5850.0
    put_wall: Optional[float] = 5750.0
    hvl: Optional[float] = None
    vol_trigger_up: Optional[float] = None
    vol_trigger_down: Optional[float] = None
    max_pain: Optional[float] = None
    data_quality: str = "live"


class FakeTVBridge:
    def __init__(self, snapshot: Optional[FakeSnapshot] = None) -> None:
        self._snapshot = snapshot or FakeSnapshot()

    def get_snapshot(self, symbol: str) -> FakeSnapshot:
        return self._snapshot


class FakeDataManager:
    def __init__(self, price: Optional[float] = 5825.5) -> None:
        self._price = price

    async def get_current_price(self, symbol: str) -> dict:
        return {"last_price": self._price, "source": "fake"}

    async def get_bars(self, symbol: str, lookback_days: int = 1, timeframe: str = "1h"):
        # Default bars; individual tests override by passing bars_fn instead.
        return pd.DataFrame(
            {
                "high": [5830.0, 5840.0],
                "low": [5810.0, 5815.0],
                "close": [5820.0, 5835.0],
            }
        )


def _make_briefing(
    directional: str = "bullish",
    conviction: float = 0.7,
    data_quality: str = "fresh",
    ib_levels: Optional[dict] = None,
) -> FakeBriefing:
    return FakeBriefing(
        corey_bias=FakeCoreyBias(
            directional_bias=directional,
            conviction=conviction,
            data_quality=data_quality,
        ),
        ib_levels=ib_levels,
    )


async def _fake_briefing_fn_factory(briefing: FakeBriefing):
    async def _fn(symbol: str, for_date=None):
        return briefing

    return _fn


def _fresh_db() -> str:
    """Create a migrated fresh sqlite DB and return its path."""
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "t.db")
    conn = sqlite3.connect(db_path)
    try:
        run_migrations(conn)
    finally:
        conn.close()
    return db_path


# ── _derive_hypothesis unit tests ─────────────────────────────────────────────


def test_derive_long_on_bullish_fresh_high_conviction():
    side, reason = _derive_hypothesis(FakeCoreyBias(), {})
    assert side == "long"
    assert "bullish" in reason


def test_derive_short_on_bearish():
    side, _ = _derive_hypothesis(
        FakeCoreyBias(directional_bias="bearish", conviction=0.75), {}
    )
    assert side == "short"


def test_derive_skip_on_stale_data_quality():
    side, reason = _derive_hypothesis(
        FakeCoreyBias(data_quality="stale"), {}
    )
    assert side == "skip"
    assert "stale" in reason


def test_derive_skip_on_low_conviction():
    side, reason = _derive_hypothesis(
        FakeCoreyBias(conviction=0.3), {}
    )
    assert side == "skip"
    assert "0.30" in reason


def test_derive_skip_on_neutral():
    side, reason = _derive_hypothesis(
        FakeCoreyBias(directional_bias="neutral"), {}
    )
    assert side == "skip"
    assert "neutral" in reason


# ── _gamma_snapshot_to_dict unit tests ────────────────────────────────────────


def test_gamma_snapshot_none_returns_unavailable():
    d = _gamma_snapshot_to_dict(None)
    assert d == {"data_quality": "unavailable"}


def test_gamma_snapshot_populated_fields():
    d = _gamma_snapshot_to_dict(FakeSnapshot(gex_flip=5800.0, call_wall=5900.0))
    assert d["gex_flip"] == 5800.0
    assert d["call_wall"] == 5900.0
    assert d["data_quality"] == "live"


# ── record_session integration tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_writes_long_row_with_full_signals(tmp_path):
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(
        _make_briefing(ib_levels={"ib_high": 5830.0, "ib_low": 5810.0})
    )
    result = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5820.0),
    )
    assert result.inserted is True
    assert result.hypothesis_side == "long"
    assert result.open_price == 5820.0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM mes_session_hypothesis WHERE date = ?",
            ("2026-04-20",),
        ).fetchone()
    assert row is not None
    assert row["corey_bias"] == "bullish"
    assert row["corey_conviction"] == 0.7
    assert row["entry_hypothesis_side"] == "long"
    gamma = json.loads(row["gamma_snapshot_json"])
    assert gamma["gex_flip"] == 5800.0
    ib = json.loads(row["ib_levels_json"])
    assert ib["ib_high"] == 5830.0


@pytest.mark.asyncio
async def test_record_idempotent_on_same_date():
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    r1 = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(),
    )
    r2 = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(),
    )
    assert r1.inserted is True
    assert r2.inserted is False  # second call is a no-op
    with sqlite3.connect(db_path) as conn:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM mes_session_hypothesis"
        ).fetchone()
    assert n == 1


@pytest.mark.asyncio
async def test_record_graceful_when_data_manager_none():
    """No data_manager → open_price=NULL but row still written."""
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    result = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=None,
    )
    assert result.inserted is True
    assert result.open_price is None
    assert "data_manager_unavailable" in result.warnings


@pytest.mark.asyncio
async def test_record_graceful_when_tv_unavailable():
    """TV bridge returning unavailable snapshot → gamma dict marks unavailable, row written."""
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    bridge = FakeTVBridge(snapshot=FakeSnapshot(
        gex_flip=None, call_wall=None, put_wall=None, data_quality="unavailable"
    ))
    result = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=bridge,
        data_manager=FakeDataManager(),
    )
    assert result.inserted is True
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT gamma_snapshot_json FROM mes_session_hypothesis LIMIT 1"
        ).fetchone()
    gamma = json.loads(row[0])
    assert gamma["data_quality"] == "unavailable"
    assert gamma["gex_flip"] is None


@pytest.mark.asyncio
async def test_record_skip_when_corey_stale():
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(
        _make_briefing(data_quality="stale")
    )
    result = await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(),
    )
    assert result.inserted is True
    assert result.hypothesis_side == "skip"


# ── _compute_delta unit tests ────────────────────────────────────────────────


def test_delta_long_positive_when_price_rises():
    assert _compute_delta("long", 5800.0, 5820.0) == pytest.approx(20.0)


def test_delta_long_negative_when_price_falls():
    assert _compute_delta("long", 5800.0, 5780.0) == pytest.approx(-20.0)


def test_delta_short_positive_when_price_falls():
    assert _compute_delta("short", 5800.0, 5780.0) == pytest.approx(20.0)


def test_delta_skip_is_zero():
    assert _compute_delta("skip", 5800.0, 5820.0) == 0.0


def test_delta_returns_none_when_open_price_missing():
    assert _compute_delta("long", None, 5820.0) is None


def test_delta_returns_none_when_close_missing():
    assert _compute_delta("long", 5800.0, None) is None


# ── _hlc_from_bars unit tests ────────────────────────────────────────────────


def test_hlc_from_bars_returns_tuple_from_dataframe():
    df = pd.DataFrame(
        {"high": [10.0, 20.0, 15.0], "low": [5.0, 12.0, 8.0], "close": [9.0, 18.0, 14.0]}
    )
    high, low, close = _hlc_from_bars(df)
    assert high == 20.0
    assert low == 5.0
    assert close == 14.0


def test_hlc_from_bars_none_input():
    assert _hlc_from_bars(None) == (None, None, None)


def test_hlc_from_bars_empty_dataframe():
    assert _hlc_from_bars(pd.DataFrame()) == (None, None, None)


# ── fill_outcomes integration tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fill_outcomes_long_row_gets_positive_delta():
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )

    async def bars_fn(symbol: str):
        return pd.DataFrame(
            {"high": [5830.0, 5840.0], "low": [5790.0, 5810.0], "close": [5820.0, 5835.0]}
        )

    result = await fill_outcomes(for_date=date(2026, 4, 20), db_path=db_path, bars_fn=bars_fn)
    assert result.updated_rows == 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT high_price, low_price, close_price, outcome_delta, outcome_recorded_at "
            "FROM mes_session_hypothesis WHERE date = ?",
            ("2026-04-20",),
        ).fetchone()
    assert row["high_price"] == 5840.0
    assert row["low_price"] == 5790.0
    assert row["close_price"] == 5835.0
    # Long: close (5835) - open (5800) = +35
    assert row["outcome_delta"] == pytest.approx(35.0)
    assert row["outcome_recorded_at"] is not None


@pytest.mark.asyncio
async def test_fill_outcomes_idempotent():
    """Second call doesn't re-touch a filled row."""
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )

    async def bars_fn(symbol: str):
        return pd.DataFrame({"high": [5830.0], "low": [5790.0], "close": [5820.0]})

    r1 = await fill_outcomes(for_date=date(2026, 4, 20), db_path=db_path, bars_fn=bars_fn)
    r2 = await fill_outcomes(for_date=date(2026, 4, 20), db_path=db_path, bars_fn=bars_fn)
    assert r1.updated_rows == 1
    # Second pass either skips or sees nothing pending — either way, no re-update
    assert r2.updated_rows == 0


@pytest.mark.asyncio
async def test_fill_outcomes_missing_bars_leaves_row_pending():
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )

    async def bars_fn(symbol: str):
        return None  # simulate no bars available

    result = await fill_outcomes(for_date=date(2026, 4, 20), db_path=db_path, bars_fn=bars_fn)
    assert result.updated_rows == 0
    assert result.skipped_no_data == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT outcome_recorded_at FROM mes_session_hypothesis LIMIT 1"
        ).fetchone()
    # Row stays pending — the outcome job can retry the next cycle
    assert row[0] is None


@pytest.mark.asyncio
async def test_fill_outcomes_skips_stale_rows_without_for_date():
    """When called bare (no for_date), only TODAY's row is filled. Stale
    rows must stay NULL rather than be filled with the wrong-day close.

    Scenario: yesterday's 15:15 CT job failed (no bars). Today at 15:15 CT,
    the scheduler calls fill_outcomes() bare. If we used today's close to
    fill yesterday's open, the outcome_delta would be 2-day, not 1-day.
    The guard must skip yesterday's row and leave it NULL.
    """
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    # Seed yesterday's row (stale) + today's row (current)
    from datetime import timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    await record_session(
        for_date=yesterday, db_path=db_path,
        briefing_fn=briefing_fn, tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )
    await record_session(
        for_date=today, db_path=db_path,
        briefing_fn=briefing_fn, tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5900.0),
    )

    async def bars_fn(symbol: str):
        return pd.DataFrame({"high": [5950.0], "low": [5880.0], "close": [5920.0]})

    result = await fill_outcomes(db_path=db_path, bars_fn=bars_fn)
    assert result.updated_rows == 1  # only today's row filled
    assert result.skipped_no_data == 1  # yesterday's row skipped

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {r["date"]: r["outcome_recorded_at"]
                for r in conn.execute(
                    "SELECT date, outcome_recorded_at FROM mes_session_hypothesis"
                ).fetchall()}
    assert rows[yesterday.isoformat()] is None, \
        "stale row must stay NULL to avoid cross-day close corruption"
    assert rows[today.isoformat()] is not None


@pytest.mark.asyncio
async def test_fill_outcomes_for_date_filter():
    db_path = _fresh_db()
    briefing_fn = await _fake_briefing_fn_factory(_make_briefing())
    await record_session(
        for_date=date(2026, 4, 17),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )
    await record_session(
        for_date=date(2026, 4, 20),
        db_path=db_path,
        briefing_fn=briefing_fn,
        tv_bridge=FakeTVBridge(),
        data_manager=FakeDataManager(price=5800.0),
    )

    async def bars_fn(symbol: str):
        return pd.DataFrame({"high": [5830.0], "low": [5790.0], "close": [5820.0]})

    result = await fill_outcomes(
        for_date=date(2026, 4, 20), db_path=db_path, bars_fn=bars_fn
    )
    assert result.updated_rows == 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT date, outcome_recorded_at FROM mes_session_hypothesis ORDER BY date"
        ).fetchall()
    # Only 2026-04-20 should have outcome filled
    by_date = {r["date"]: r["outcome_recorded_at"] for r in rows}
    assert by_date["2026-04-17"] is None
    assert by_date["2026-04-20"] is not None
