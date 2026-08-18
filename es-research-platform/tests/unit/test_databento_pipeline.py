from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from es_research.features.bars import build_time_bars
from es_research.ingestion.databento import (
    DatabentoRequest,
    ingest_databento_dbn,
    verify_bronze_artifact,
)
from es_research.normalization.databento import normalize_databento_trades
from es_research.sessionization.calendar import assign_sessions
from es_research.sessionization.es_fixtures import es_session_fixtures
from es_research.validation.pipeline import validate_bars, validate_normalized_trade_rows


class _FakeResponse:
    def to_file(self, path: str) -> None:
        Path(path).write_bytes(b"DBN synthetic test payload")


class _FakeTimeseries:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def get_range(self, **kwargs: object) -> _FakeResponse:
        self.kwargs = kwargs
        return _FakeResponse()


class _FakeClient:
    def __init__(self) -> None:
        self.timeseries = _FakeTimeseries()


def _request() -> DatabentoRequest:
    return DatabentoRequest(
        dataset="GLBX.MDP3",
        schema="trades",
        symbols=("ES.FUT",),
        start=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        end=datetime(2026, 1, 5, 14, 35, tzinfo=UTC),
    )


def _records() -> tuple[dict[str, Any], ...]:
    base = 1_767_623_400_000_000_000
    return tuple(
        {
            "instrument_id": 12345,
            "price": 5_000_000_000_000 + offset * 250_000_000,
            "publisher_id": 1,
            "sequence": offset + 1,
            "side": "A" if offset % 2 == 0 else "B",
            "size": 1,
            "ts_event": base + offset * 60_000_000_000,
            "ts_recv": base + offset * 60_000_000_000 + 1_000,
        }
        for offset in range(6)
    )


def test_bronze_download_is_hashed_verified_and_immutable(tmp_path: Path) -> None:
    client = _FakeClient()
    path = tmp_path / "bronze" / "es-trades.dbn.zst"
    artifact = ingest_databento_dbn(client, _request(), path)
    assert artifact.sha256 == hashlib.sha256(b"DBN synthetic test payload").hexdigest()
    assert client.timeseries.kwargs["schema"] == "trades"
    verify_bronze_artifact(artifact)
    with pytest.raises(FileExistsError, match="immutable bronze"):
        ingest_databento_dbn(client, _request(), path)


def test_bronze_verification_detects_mutation(tmp_path: Path) -> None:
    artifact = ingest_databento_dbn(_FakeClient(), _request(), tmp_path / "trades.dbn.zst")
    artifact.data_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="byte count changed"):
        verify_bronze_artifact(artifact)


def test_databento_records_normalize_and_build_valid_bars() -> None:
    rows = normalize_databento_trades(_records(), symbol_by_instrument={12345: "ESH6"})
    validate_normalized_trade_rows(rows)
    assigned = assign_sessions(rows, es_session_fixtures())
    bars = build_time_bars(assigned)
    validate_bars(bars)
    assert rows[0]["price"] == Decimal("5000.000000000")
    assert rows[0]["aggressor_side"] == "buy"
    assert len(bars) == 2
    assert bars[0].open == Decimal("5000.000000000")
    assert bars[0].close == Decimal("5001.000000000")
    assert bars[0].volume == Decimal("5")


def test_databento_normalization_rejects_unknown_instrument() -> None:
    with pytest.raises(ValueError, match="missing symbol mapping"):
        normalize_databento_trades(_records(), symbol_by_instrument={})
