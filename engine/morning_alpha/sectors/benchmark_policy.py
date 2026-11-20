from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict


class BenchmarkUnavailable(ValueError):
    """Raised when a historical observation has no valid canonical sector benchmark."""


class SectorBenchmark(BaseModel):
    model_config = ConfigDict(frozen=True)

    gics_sector_code: str
    sector_name: str
    ticker: str
    inception: datetime


_LEGACY_INCEPTION = datetime(1998, 12, 16, tzinfo=UTC)

_SECTOR_BENCHMARKS: dict[str, SectorBenchmark] = {
    "10": SectorBenchmark(gics_sector_code="10", sector_name="Energy", ticker="XLE", inception=_LEGACY_INCEPTION),
    "15": SectorBenchmark(gics_sector_code="15", sector_name="Materials", ticker="XLB", inception=_LEGACY_INCEPTION),
    "20": SectorBenchmark(gics_sector_code="20", sector_name="Industrials", ticker="XLI", inception=_LEGACY_INCEPTION),
    "25": SectorBenchmark(gics_sector_code="25", sector_name="Consumer Discretionary", ticker="XLY", inception=_LEGACY_INCEPTION),
    "30": SectorBenchmark(gics_sector_code="30", sector_name="Consumer Staples", ticker="XLP", inception=_LEGACY_INCEPTION),
    "35": SectorBenchmark(gics_sector_code="35", sector_name="Health Care", ticker="XLV", inception=_LEGACY_INCEPTION),
    "40": SectorBenchmark(gics_sector_code="40", sector_name="Financials", ticker="XLF", inception=_LEGACY_INCEPTION),
    "45": SectorBenchmark(gics_sector_code="45", sector_name="Information Technology", ticker="XLK", inception=_LEGACY_INCEPTION),
    "50": SectorBenchmark(
        gics_sector_code="50",
        sector_name="Communication Services",
        ticker="XLC",
        inception=datetime(2018, 6, 18, tzinfo=UTC),
    ),
    "55": SectorBenchmark(gics_sector_code="55", sector_name="Utilities", ticker="XLU", inception=_LEGACY_INCEPTION),
    "60": SectorBenchmark(
        gics_sector_code="60",
        sector_name="Real Estate",
        ticker="XLRE",
        inception=datetime(2015, 10, 7, tzinfo=UTC),
    ),
}


def _sector_code(gics: str | None) -> str:
    if not gics or len(gics) < 2 or not gics[:2].isdigit():
        raise BenchmarkUnavailable(f"invalid or missing GICS code: {gics!r}")
    code = gics[:2]
    if code not in _SECTOR_BENCHMARKS:
        raise BenchmarkUnavailable(f"unsupported GICS sector code: {code}")
    return code


def sector_benchmark_for_gics(gics: str | None, *, as_of: datetime) -> SectorBenchmark:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    benchmark = _SECTOR_BENCHMARKS[_sector_code(gics)]
    if as_of.astimezone(UTC) < benchmark.inception:
        raise BenchmarkUnavailable(
            f"{benchmark.ticker} unavailable before {benchmark.inception.date().isoformat()}"
        )
    return benchmark


def sector_benchmark_for_ticker(ticker: str, *, as_of: datetime) -> SectorBenchmark:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    normalized = ticker.upper()
    benchmark = next((b for b in _SECTOR_BENCHMARKS.values() if b.ticker == normalized), None)
    if benchmark is None:
        raise BenchmarkUnavailable(f"unsupported sector benchmark ticker: {ticker}")
    if as_of.astimezone(UTC) < benchmark.inception:
        raise BenchmarkUnavailable(
            f"{benchmark.ticker} unavailable before {benchmark.inception.date().isoformat()}"
        )
    return benchmark


def sector_benchmark_available(ticker: str, *, as_of: datetime) -> bool:
    try:
        sector_benchmark_for_ticker(ticker, as_of=as_of)
    except BenchmarkUnavailable:
        return False
    return True


def earliest_complete_sector_benchmark_date() -> datetime:
    """Earliest timestamp at which all 11 canonical Select Sector SPDR benchmarks exist."""
    return max(benchmark.inception for benchmark in _SECTOR_BENCHMARKS.values())
