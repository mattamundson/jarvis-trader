from datetime import UTC, datetime, timedelta

from morning_alpha.models import SetupCandidate, StrategyKey
from morning_alpha.research.controls import ControlKind, ControlSelector, UniverseMember

AS_OF = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)


def candidate(**overrides):
    values = dict(
        symbol="AAA",
        strategy=StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        as_of=AS_OF,
        side="long",
        setup_type="relative_strength_breakout",
        thesis_code="rs_breakout",
        proposed_entry=101.0,
        proposed_stop=98.0,
        sector="Technology",
    )
    values.update(overrides)
    return SetupCandidate(**values)


def member(symbol: str, sector: str = "Technology", **overrides):
    values = dict(
        symbol=symbol,
        sector=sector,
        effective_from=AS_OF - timedelta(days=365),
        effective_to=None,
        eligible=True,
    )
    values.update(overrides)
    return UniverseMember(**values)


def test_control_selection_is_deterministic_for_same_seed_namespace():
    universe = [member("BBB"), member("CCC"), member("DDD", sector="Financials")]
    selector = ControlSelector()

    first = selector.select(candidate(), universe, sector_etf="XLK", seed_namespace="sprint1")
    second = selector.select(candidate(), universe, sector_etf="XLK", seed_namespace="sprint1")

    assert first == second
    assert {row.kind for row in first} == set(ControlKind)
    assert all(row.as_of == AS_OF for row in first)


def test_future_or_expired_members_never_enter_random_controls():
    universe = [
        member("ACTIVE"),
        member("FUTURE", effective_from=AS_OF + timedelta(days=1)),
        member("EXPIRED", effective_to=AS_OF),
        member("INELIGIBLE", eligible=False),
    ]

    rows = ControlSelector().select(candidate(), universe, sector_etf="XLK", seed_namespace="sprint1")
    random_rows = [
        row for row in rows if row.kind in {ControlKind.RANDOM_UNIVERSE, ControlKind.RANDOM_SAME_SECTOR}
    ]

    assert {row.symbol for row in random_rows if row.available} == {"ACTIVE"}


def test_same_sector_control_is_explicitly_unavailable_when_pool_is_empty():
    universe = [member("FIN", sector="Financials")]

    rows = ControlSelector().select(candidate(), universe, sector_etf="XLK", seed_namespace="sprint1")
    same_sector = next(row for row in rows if row.kind is ControlKind.RANDOM_SAME_SECTOR)

    assert same_sector.available is False
    assert same_sector.symbol is None
    assert same_sector.reason == "NO_SAME_SECTOR_CONTROL"


def test_candidate_symbol_is_not_used_as_random_control():
    universe = [member("AAA"), member("BBB")]

    rows = ControlSelector().select(candidate(), universe, sector_etf="XLK", seed_namespace="sprint1")

    for row in rows:
        if row.kind in {ControlKind.RANDOM_UNIVERSE, ControlKind.RANDOM_SAME_SECTOR} and row.available:
            assert row.symbol != "AAA"


def test_benchmark_and_same_stock_controls_have_fixed_identity():
    rows = ControlSelector().select(
        candidate(), [member("BBB")], sector_etf="XLK", seed_namespace="sprint1"
    )
    by_kind = {row.kind: row for row in rows}

    assert by_kind[ControlKind.NEXT_OPEN].symbol == "AAA"
    assert by_kind[ControlKind.SPY].symbol == "SPY"
    assert by_kind[ControlKind.SECTOR_ETF].symbol == "XLK"
    assert by_kind[ControlKind.NEXT_OPEN].available is True
    assert by_kind[ControlKind.SECTOR_ETF].available is True


def test_missing_sector_etf_is_unavailable_not_guessed():
    rows = ControlSelector().select(
        candidate(), [member("BBB")], sector_etf=None, seed_namespace="sprint1"
    )
    sector = next(row for row in rows if row.kind is ControlKind.SECTOR_ETF)
    assert sector.available is False
    assert sector.symbol is None
    assert sector.reason == "SECTOR_ETF_UNAVAILABLE"
