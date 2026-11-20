from datetime import UTC, datetime

import pytest

from morning_alpha.sectors.benchmark_policy import (
    BenchmarkUnavailable,
    earliest_complete_sector_benchmark_date,
    sector_benchmark_for_gics,
)


def ts(year: int, month: int, day: int):
    return datetime(year, month, day, tzinfo=UTC)


def test_gics_sector_codes_map_to_canonical_select_sector_etfs():
    assert sector_benchmark_for_gics("10102010", as_of=ts(2026, 9, 15)).ticker == "XLE"
    assert sector_benchmark_for_gics("40101010", as_of=ts(2026, 9, 15)).ticker == "XLF"
    assert sector_benchmark_for_gics("45103010", as_of=ts(2026, 9, 15)).ticker == "XLK"
    assert sector_benchmark_for_gics("50202010", as_of=ts(2026, 9, 15)).ticker == "XLC"
    assert sector_benchmark_for_gics("60101010", as_of=ts(2026, 9, 15)).ticker == "XLRE"


def test_xlc_is_fail_closed_before_its_real_inception():
    with pytest.raises(BenchmarkUnavailable, match="XLC"):
        sector_benchmark_for_gics("50202010", as_of=ts(2018, 6, 17))
    assert sector_benchmark_for_gics("50202010", as_of=ts(2018, 6, 18)).ticker == "XLC"


def test_xlre_is_fail_closed_before_its_real_inception():
    with pytest.raises(BenchmarkUnavailable, match="XLRE"):
        sector_benchmark_for_gics("60101010", as_of=ts(2015, 10, 6))
    assert sector_benchmark_for_gics("60101010", as_of=ts(2015, 10, 7)).ticker == "XLRE"


def test_complete_eleven_sector_window_starts_when_xlc_exists():
    assert earliest_complete_sector_benchmark_date() == ts(2018, 6, 18)


def test_unknown_or_malformed_gics_is_rejected_not_guessed():
    for value in (None, "", "99", "XX101010"):
        with pytest.raises(BenchmarkUnavailable):
            sector_benchmark_for_gics(value, as_of=ts(2026, 9, 15))
