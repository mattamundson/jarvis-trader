"""Regression test: Bug C (T2-19) from the 2026-07-11 dashboard audit.

`GET /paper/mgc-signal` was showing "SIGNAL DATE: 250" on the Paper trading
page. Root cause: when the signals DataFrame's index is a plain positional
RangeIndex (the common case for this pipeline -- see data/market_data.py,
which returns OHLCV frames with a `timestamp` column and never sets a
DatetimeIndex), `_generate_signal()` stringified the raw positional integer
(e.g. row 250) as if it were a date, instead of reading the real timestamp
column.

`_derive_signal_date()` in routers/backtest_router.py is the extracted fix:
it prefers a DatetimeIndex when present, and otherwise falls back to the
real `timestamp`/`date` column on the dataframe.
"""

from __future__ import annotations

import pandas as pd

from routers.backtest_router import _derive_signal_date


def test_range_index_with_timestamp_column_derives_real_date():
    """The common case: plain RangeIndex + a 'timestamp' column (what
    data_manager.get_bars() actually returns). Must NOT return the
    positional row number stringified (e.g. "250")."""
    n_bars = 260
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n_bars, freq="D"),
            "close": range(n_bars),
        }
    )
    assert isinstance(df.index, pd.RangeIndex)

    result = _derive_signal_date(df)

    last_real_date = str(df["timestamp"].iloc[-1].date())
    assert result == last_real_date
    # The historical bug: str(df.index[-1])[:10] == "259" for a 260-row frame.
    assert result != str(df.index[-1])
    assert result != "250"


def test_range_index_with_date_column_derives_real_date():
    """Same bug, but the real column is named 'date' instead of 'timestamp'."""
    n_bars = 50
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-06-01", periods=n_bars, freq="D"),
            "close": range(n_bars),
        }
    )
    result = _derive_signal_date(df)
    assert result == str(df["date"].iloc[-1].date())


def test_datetime_index_still_works():
    """Existing/working path: a real DatetimeIndex must continue to be used
    directly and must not regress."""
    n_bars = 30
    idx = pd.date_range("2025-03-01", periods=n_bars, freq="D")
    df = pd.DataFrame({"close": range(n_bars)}, index=idx)
    assert isinstance(df.index, pd.DatetimeIndex)

    result = _derive_signal_date(df)

    assert result == str(idx[-1].date())


def test_no_datetime_source_falls_back_without_crashing():
    """Pathological case: no DatetimeIndex and no timestamp/date column.
    Must not raise, and must not stringify the positional row number."""
    df = pd.DataFrame({"close": range(5)})
    result = _derive_signal_date(df)

    # Falls back to "today" (UTC) rather than the positional index (4).
    assert result != str(df.index[-1])
    # Sanity: still parses as a real calendar date (YYYY-MM-DD).
    parsed = pd.to_datetime(result)
    assert parsed is not None
