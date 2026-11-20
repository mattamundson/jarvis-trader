from datetime import UTC, datetime, timedelta

import pytest

from morning_alpha.models import MarketBar, Session
from morning_alpha.research.feature_builder import HistoricalFeatureBuilder


def _weekday_bars(symbol: str, start: datetime, count: int, *, base: float = 100.0):
    rows = []
    day = start
    i = 0
    while len(rows) < count:
        if day.weekday() < 5:
            close = base + i * 0.5
            rows.append(
                MarketBar(
                    symbol=symbol,
                    timestamp=day.replace(hour=20, minute=0),
                    open=close - 0.2,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=1_000_000 + i * 1000,
                    session=Session.RTH,
                    source="fixture",
                    ingested_at=day.replace(hour=20, minute=1),
                )
            )
            i += 1
        day += timedelta(days=1)
    return rows


def _fixture():
    start = datetime(2023, 6, 1, tzinfo=UTC)
    stock = _weekday_bars("AAA", start, 252, base=100)
    spy = _weekday_bars("SPY", start, 252, base=400)
    sector = _weekday_bars("XLK", start, 252, base=180)
    last_date = stock[-1].timestamp.date()
    decision = datetime.combine(last_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC).replace(hour=13)
    while decision.weekday() >= 5:
        decision += timedelta(days=1)
    return stock, spy, sector, decision


def test_feature_builder_uses_completed_sessions_and_computes_rs_features():
    stock, spy, sector, decision = _fixture()
    result = HistoricalFeatureBuilder().build(
        stable_security_id="SEC-AAA",
        symbol="AAA",
        sector="Technology",
        sector_etf="XLK",
        decision_timestamp=decision,
        data_manifest_hash="d" * 64,
        stock_bars=stock,
        spy_bars=spy,
        sector_bars=sector,
    )
    assert result.previous_close == stock[-1].close
    assert result.prior_high == stock[-1].high
    assert result.prior_low == stock[-1].low
    assert result.sma20 > result.sma50
    assert result.returns_20d > 0
    assert result.spy_return_20d > 0
    assert result.sector_return_20d > 0
    assert result.latest_source_timestamp < decision
    assert len(result.feature_hash) == 64
    assert len(result.source_lineage_hash) == 64


def test_adding_future_bars_does_not_change_feature_snapshot_or_hash():
    stock, spy, sector, decision = _fixture()
    builder = HistoricalFeatureBuilder()
    base = builder.build(
        stable_security_id="SEC-AAA", symbol="AAA", sector="Technology", sector_etf="XLK",
        decision_timestamp=decision, data_manifest_hash="d" * 64,
        stock_bars=stock, spy_bars=spy, sector_bars=sector,
    )
    absurd_ts = decision + timedelta(hours=8)
    future = MarketBar(
        symbol="AAA", timestamp=absurd_ts, open=10_000, high=20_000, low=9_000, close=19_000,
        volume=99_000_000, session=Session.RTH, source="future", ingested_at=absurd_ts,
    )
    future_spy = future.model_copy(update={"symbol": "SPY"})
    future_sector = future.model_copy(update={"symbol": "XLK"})
    again = builder.build(
        stable_security_id="SEC-AAA", symbol="AAA", sector="Technology", sector_etf="XLK",
        decision_timestamp=decision, data_manifest_hash="d" * 64,
        stock_bars=stock + [future], spy_bars=spy + [future_spy], sector_bars=sector + [future_sector],
    )
    assert again.model_dump(mode="json") == base.model_dump(mode="json")


def test_same_trading_day_daily_bar_is_excluded_even_if_timestamp_precedes_decision():
    stock, spy, sector, decision = _fixture()
    same_day = MarketBar(
        symbol="AAA", timestamp=decision - timedelta(hours=1), open=999, high=1000, low=998, close=999,
        volume=50_000_000, session=Session.RTH, source="bad_daily", ingested_at=decision - timedelta(minutes=50),
    )
    result = HistoricalFeatureBuilder().build(
        stable_security_id="SEC-AAA", symbol="AAA", sector="Technology", sector_etf="XLK",
        decision_timestamp=decision, data_manifest_hash="d" * 64,
        stock_bars=stock + [same_day], spy_bars=spy, sector_bars=sector,
    )
    assert result.previous_close == stock[-1].close


def test_benchmark_endpoint_mismatch_fails_closed():
    stock, spy, sector, decision = _fixture()
    with pytest.raises(ValueError, match="BENCHMARK_ALIGNMENT_FAILED"):
        HistoricalFeatureBuilder().build(
            stable_security_id="SEC-AAA", symbol="AAA", sector="Technology", sector_etf="XLK",
            decision_timestamp=decision, data_manifest_hash="d" * 64,
            stock_bars=stock, spy_bars=spy[:-1], sector_bars=sector,
        )


def test_feature_builder_rejects_insufficient_history():
    stock, spy, sector, decision = _fixture()
    with pytest.raises(ValueError, match="INSUFFICIENT_HISTORY"):
        HistoricalFeatureBuilder().build(
            stable_security_id="SEC-AAA", symbol="AAA", sector="Technology", sector_etf="XLK",
            decision_timestamp=decision, data_manifest_hash="d" * 64,
            stock_bars=stock[-100:], spy_bars=spy, sector_bars=sector,
        )
