"""Databento bronze-to-silver acceptance pipeline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from es_research.contracts import SessionCalendar
from es_research.features.bars import build_time_bars
from es_research.hashing import sha256_hash
from es_research.normalization.databento import decode_databento_trades, normalize_databento_trades
from es_research.normalization.events import (
    NORMALIZED_TRADE_SCHEMA_VERSION,
    read_normalized_trades_parquet,
    write_normalized_trades_parquet,
)
from es_research.sessionization.calendar import assign_sessions
from es_research.validation.pipeline import validate_bars, validate_normalized_trade_rows


@dataclass(frozen=True)
class DatabentoPipelineResult:
    bronze_sha256: str
    instrument_map_hash: str
    session_calendar_hash: str
    silver_rows_hash: str
    bars_hash: str
    row_count: int
    bar_count: int
    minimum_timestamp: str
    maximum_timestamp: str
    silver_path: Path
    report_path: Path


def run_databento_pipeline(
    bronze_path: Path,
    output_dir: Path,
    *,
    symbol_by_instrument: Mapping[int, str],
    sessions: tuple[SessionCalendar, ...],
    instrument_map_hash: str,
    session_calendar_hash: str,
    decoded_records: Iterable[Mapping[str, Any]] | None = None,
) -> DatabentoPipelineResult:
    """Normalize DBN trades, round-trip silver Parquet, build bars, and record provenance."""
    if not bronze_path.is_file():
        raise FileNotFoundError(f"Databento bronze file does not exist: {bronze_path}")
    records = decode_databento_trades(bronze_path) if decoded_records is None else decoded_records
    normalized = normalize_databento_trades(records, symbol_by_instrument=symbol_by_instrument)
    if not normalized:
        raise ValueError("Databento bronze file produced no trade rows")
    validate_normalized_trade_rows(normalized)

    output_dir.mkdir(parents=True, exist_ok=True)
    silver_path = output_dir / "normalized_trades.parquet"
    report_path = output_dir / "acceptance_report.json"
    write_normalized_trades_parquet(normalized, silver_path)
    restored = read_normalized_trades_parquet(silver_path)
    validate_normalized_trade_rows(restored)
    if restored != normalized:
        raise ValueError("normalized Parquet read-back differs from in-memory silver rows")

    bars = build_time_bars(assign_sessions(restored, sessions))
    validate_bars(bars)
    result = DatabentoPipelineResult(
        bronze_sha256=_file_sha256(bronze_path),
        instrument_map_hash=instrument_map_hash,
        session_calendar_hash=session_calendar_hash,
        silver_rows_hash=sha256_hash(restored),
        bars_hash=sha256_hash(tuple(asdict(bar) for bar in bars)),
        row_count=len(restored),
        bar_count=len(bars),
        minimum_timestamp=min(row["event_timestamp"] for row in restored).isoformat(),
        maximum_timestamp=max(row["event_timestamp"] for row in restored).isoformat(),
        silver_path=silver_path,
        report_path=report_path,
    )
    report = {
        **asdict(result),
        "schema_version": NORMALIZED_TRADE_SCHEMA_VERSION,
        "silver_path": str(silver_path),
        "report_path": str(report_path),
    }
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
