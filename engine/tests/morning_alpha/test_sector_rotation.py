from datetime import UTC, datetime

import pytest

from morning_alpha.models import SectorSnapshot
from morning_alpha.sectors import SECTOR_ETFS, SectorRotationEngine

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


def snapshot(symbol: str, strength: float, *, as_of=AS_OF):
    return SectorSnapshot(
        symbol=symbol,
        sector=symbol,
        as_of=as_of,
        returns_1d=strength / 4,
        returns_5d=strength,
        returns_20d=strength * 1.5,
        returns_50d=strength * 2,
        relative_to_spy_20d=strength,
        distance_from_52w_high=-0.10 + strength,
        volume_acceleration=1.0 + strength,
        source="fixture",
    )


def test_sector_universe_has_all_11_canonical_etfs():
    assert SECTOR_ETFS == (
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLC", "XLB", "XLU", "XLRE"
    )


def test_sector_rank_is_deterministic_and_preserves_components():
    rows = [snapshot(symbol, idx / 100) for idx, symbol in enumerate(SECTOR_ETFS)]
    ranked = SectorRotationEngine().rank(rows)
    assert len(ranked) == 11
    assert ranked[0].symbol == SECTOR_ETFS[-1]
    assert ranked[0].rank == 1
    assert ranked[-1].rank == 11
    assert ranked[0].score_version == "sector_rotation_score@0.1.0-research"
    assert set(ranked[0].normalized_components) == {
        "relative_to_spy_20d",
        "returns_5d",
        "returns_20d",
        "returns_50d",
        "distance_from_52w_high",
        "volume_acceleration",
    }
    assert ranked[0].confidence == pytest.approx(1.0)


def test_sector_score_confidence_tracks_missing_features():
    row = snapshot("XLK", 0.1).model_copy(update={"volume_acceleration": None})
    ranked = SectorRotationEngine().rank([row])
    assert ranked[0].confidence == pytest.approx(0.9)


def test_sector_rank_rejects_mixed_as_of_timestamps():
    other = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="same as_of"):
        SectorRotationEngine().rank([snapshot("XLK", 0.1), snapshot("XLF", 0.2, as_of=other)])


def test_sector_rank_excludes_benchmarks_that_did_not_exist_as_of_timestamp():
    before_xlc = datetime(2018, 6, 17, 13, 0, tzinfo=UTC)
    rows = [snapshot(symbol, idx / 100, as_of=before_xlc) for idx, symbol in enumerate(SECTOR_ETFS)]
    ranked = SectorRotationEngine().rank(rows)
    assert "XLC" not in {row.symbol for row in ranked}
    assert "XLRE" in {row.symbol for row in ranked}
    assert len(ranked) == 10
