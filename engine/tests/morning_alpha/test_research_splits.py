from datetime import UTC, date, datetime, timedelta

import pytest

from morning_alpha.research.splits import SplitKind, SplitRegistry, TemporalSplit


def _trading_dates(start: date, count: int):
    rows = []
    current = start
    while len(rows) < count:
        if current.weekday() < 5:
            rows.append(current)
        current += timedelta(days=1)
    return tuple(rows)


def test_split_registry_rejects_overlap():
    with pytest.raises(ValueError, match="overlap"):
        SplitRegistry(splits=(TemporalSplit(kind=SplitKind.DEVELOPMENT,start=date(2020,1,1),end=date(2020,6,30)),TemporalSplit(kind=SplitKind.VALIDATION,start=date(2020,6,1),end=date(2020,12,31))),trading_dates=_trading_dates(date(2020,1,1),260))


def test_split_registry_requires_chronological_kind_order():
    with pytest.raises(ValueError, match="chronological"):
        SplitRegistry(splits=(TemporalSplit(kind=SplitKind.OOS,start=date(2020,1,1),end=date(2020,3,31)),TemporalSplit(kind=SplitKind.DEVELOPMENT,start=date(2020,4,1),end=date(2020,6,30))),trading_dates=_trading_dates(date(2020,1,1),130))


def test_assign_returns_exact_disjoint_split():
    dates=_trading_dates(date(2020,1,1),80)
    registry=SplitRegistry(splits=(TemporalSplit(kind=SplitKind.DEVELOPMENT,start=dates[0],end=dates[29]),TemporalSplit(kind=SplitKind.VALIDATION,start=dates[30],end=dates[49]),TemporalSplit(kind=SplitKind.OOS,start=dates[50],end=dates[69]),TemporalSplit(kind=SplitKind.FORWARD,start=dates[70],end=dates[79])),trading_dates=dates,purge_sessions=5)
    assert registry.assign(datetime.combine(dates[10],datetime.min.time(),tzinfo=UTC)) is SplitKind.DEVELOPMENT
    assert registry.assign(datetime.combine(dates[35],datetime.min.time(),tzinfo=UTC)) is SplitKind.VALIDATION
    assert registry.assign(datetime(2019,1,1,tzinfo=UTC)) is None


def test_purge_uses_trading_session_indices_on_both_sides_of_boundaries():
    dates=_trading_dates(date(2020,1,1),80)
    registry=SplitRegistry(splits=(TemporalSplit(kind=SplitKind.DEVELOPMENT,start=dates[0],end=dates[29]),TemporalSplit(kind=SplitKind.VALIDATION,start=dates[30],end=dates[49]),TemporalSplit(kind=SplitKind.OOS,start=dates[50],end=dates[69]),TemporalSplit(kind=SplitKind.FORWARD,start=dates[70],end=dates[79])),trading_dates=dates,purge_sessions=5)
    dev=registry.purged(SplitKind.DEVELOPMENT); val=registry.purged(SplitKind.VALIDATION)
    assert dev.excluded_dates==dates[25:30]
    assert dev.included_dates[-1]==dates[24]
    assert val.excluded_dates==dates[30:35]+dates[45:50]
    assert val.included_dates==dates[35:45]


def test_default_purge_is_twenty_sessions():
    dates=_trading_dates(date(2020,1,1),100)
    registry=SplitRegistry(splits=(TemporalSplit(kind=SplitKind.DEVELOPMENT,start=dates[0],end=dates[49]),TemporalSplit(kind=SplitKind.OOS,start=dates[50],end=dates[99])),trading_dates=dates)
    assert registry.purge_sessions==20
    assert len(registry.purged(SplitKind.DEVELOPMENT).excluded_dates)==20
    assert len(registry.purged(SplitKind.OOS).excluded_dates)==20
