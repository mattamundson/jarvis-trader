import pandas as pd
from features_extra import dalton_open_type, one_timeframing_count, is_nr_n, is_inside_day


def _bars(ohlc):
    idx = pd.date_range("2026-01-02 08:30", periods=len(ohlc), freq="min", tz="America/Chicago")
    return pd.DataFrame(ohlc, index=idx, columns=["open", "high", "low", "close"])


def test_open_auction_flat():
    rows = []
    for i in range(30):
        rows.append([100, 100.5, 99.5, 100.1])
    ot, drive = dalton_open_type(_bars(rows))
    assert ot == "open_auction"
    assert abs(drive) < 1


def test_nr4():
    assert is_nr_n([10, 12, 11, 5], 4) == 1
    assert is_nr_n([10, 12, 11, 13], 4) == 0
    assert is_nr_n([10, 12], 4) is None


def test_inside():
    assert is_inside_day(110, 100, 108, 102) == 1
    assert is_inside_day(110, 100, 112, 102) == 0


def test_otf_up():
    # 3x 30m bars trending up
    rows = []
    for b in range(3):
        base = 100 + b * 5
        for i in range(30):
            rows.append([base, base + 4, base - 0.5, base + 3])
    n = one_timeframing_count(_bars(rows), bar_minutes=30, max_bars=3)
    assert n is not None and n >= 1
