"""End-to-end deterministic synthetic data pipeline demo."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from es_research.contracts import SessionCalendar
from es_research.features.bars import Bar, build_time_bars
from es_research.hashing import sha256_hash
from es_research.ingestion.synthetic import SyntheticTradeConfig, generate_synthetic_trades
from es_research.manifests.models import DataManifest, SourceFileRecord
from es_research.normalization.events import (
    normalize_trade_events,
    read_normalized_trades_parquet,
    write_normalized_trades_parquet,
)
from es_research.sessionization.calendar import assign_sessions
from es_research.validation.pipeline import validate_bars, validate_normalized_trade_rows

PIPELINE_TIME = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
PIPELINE_SCHEMA_VERSION = "phase2.synthetic.v1"
PIPELINE_CODE_COMMIT = "synthetic-pipeline-demo"


@dataclass(frozen=True)
class SyntheticPipelineResult:
    manifest_hash: str
    normalized_rows_hash: str
    bars_hash: str
    parquet_sha256: str
    report_hash: str
    row_count: int
    bar_count: int
    parquet_path: Path
    report_path: Path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bar_to_hashable(bar: Bar) -> dict[str, Any]:
    return {
        "instrument_id": bar.instrument_id,
        "symbol": bar.symbol,
        "session_id": bar.session_id,
        "bar_start": bar.bar_start,
        "bar_end": bar.bar_end,
        "timeframe": bar.timeframe,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "trade_count": bar.trade_count,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    path.write_text(serialized + "\n", encoding="utf-8")
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def synthetic_session_calendar() -> SessionCalendar:
    """Return the fixed session calendar used by the synthetic acceptance demo."""
    return SessionCalendar(
        session_id="2026-01-05_GLOBEX",
        trade_date=PIPELINE_TIME.date(),
        session_open=PIPELINE_TIME,
        session_close=PIPELINE_TIME + timedelta(hours=23),
        regular_trading_hours_open=PIPELINE_TIME,
        regular_trading_hours_close=PIPELINE_TIME + timedelta(hours=6, minutes=45),
        timezone="America/Chicago",
    )


def synthetic_trade_config() -> SyntheticTradeConfig:
    """Return deterministic synthetic trade generation settings."""
    return SyntheticTradeConfig(
        instrument_id="ESH6",
        symbol="/ES",
        venue="CME",
        start_timestamp=PIPELINE_TIME,
        event_count=12,
        interval_seconds=60,
        start_price=Decimal("5000.00"),
        quantity=Decimal("1"),
        random_seed=42,
    )


def run_synthetic_pipeline(output_dir: Path) -> SyntheticPipelineResult:
    """Run synthetic events through Parquet, session assignment, bars, validation, and hashes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "normalized_trades.parquet"
    report_path = output_dir / "pipeline_report.json"

    events = generate_synthetic_trades(synthetic_trade_config())
    normalized_rows = normalize_trade_events(events)
    validate_normalized_trade_rows(normalized_rows)

    write_normalized_trades_parquet(normalized_rows, parquet_path)
    parquet_sha256 = _file_sha256(parquet_path)

    parquet_rows = read_normalized_trades_parquet(parquet_path)
    validate_normalized_trade_rows(parquet_rows)

    assigned_rows = assign_sessions(parquet_rows, (synthetic_session_calendar(),))
    bars = build_time_bars(assigned_rows, interval=timedelta(minutes=5))
    validate_bars(bars)

    min_timestamp = min(row["event_timestamp"] for row in parquet_rows)
    max_timestamp = max(row["event_timestamp"] for row in parquet_rows)
    manifest = DataManifest(
        source_files=(
            SourceFileRecord(
                path=str(parquet_path),
                sha256=parquet_sha256,
                row_count=len(parquet_rows),
                min_timestamp=min_timestamp,
                max_timestamp=max_timestamp,
            ),
        ),
        schema_version=PIPELINE_SCHEMA_VERSION,
        generation_timestamp=PIPELINE_TIME,
        code_commit=PIPELINE_CODE_COMMIT,
    )

    normalized_rows_hash = sha256_hash(parquet_rows)
    bars_hash = sha256_hash(tuple(_bar_to_hashable(bar) for bar in bars))
    report_payload = {
        "bar_count": len(bars),
        "bars_hash": bars_hash,
        "manifest_hash": manifest.manifest_hash,
        "normalized_rows_hash": normalized_rows_hash,
        "parquet_sha256": parquet_sha256,
        "row_count": len(parquet_rows),
        "schema_version": PIPELINE_SCHEMA_VERSION,
    }
    report_hash = _write_report(report_path, report_payload)

    return SyntheticPipelineResult(
        manifest_hash=manifest.manifest_hash,
        normalized_rows_hash=normalized_rows_hash,
        bars_hash=bars_hash,
        parquet_sha256=parquet_sha256,
        report_hash=report_hash,
        row_count=len(parquet_rows),
        bar_count=len(bars),
        parquet_path=parquet_path,
        report_path=report_path,
    )
