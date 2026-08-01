from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from es_research.demo import run_reproducibility_demo
from es_research.pipeline.synthetic import run_synthetic_pipeline


def default_registry_path() -> Path:
    return Path(os.getenv("ES_RESEARCH_REGISTRY_PATH", "data/registry/experiments.duckdb"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m es_research")
    subparsers = parser.add_subparsers(dest="area", required=True)
    registry_parser = subparsers.add_parser("registry")
    registry_sub = registry_parser.add_subparsers(dest="command", required=True)
    registry_sub.add_parser("init")
    demo_parser = subparsers.add_parser("demo")
    demo_sub = demo_parser.add_subparsers(dest="command", required=True)
    demo_sub.add_parser("reproducibility")
    synthetic_parser = demo_sub.add_parser("synthetic-pipeline")
    synthetic_parser.add_argument(
        "--output-dir", type=Path, default=Path("data/silver/synthetic_demo")
    )
    data_parser = subparsers.add_parser("data")
    data_sub = data_parser.add_subparsers(dest="command", required=True)
    databento_parser = data_sub.add_parser("ingest-databento")
    databento_parser.add_argument("--dataset", required=True)
    databento_parser.add_argument("--schema", default="trades")
    databento_parser.add_argument("--symbol", action="append", required=True, dest="symbols")
    databento_parser.add_argument("--start", required=True, type=datetime.fromisoformat)
    databento_parser.add_argument("--end", required=True, type=datetime.fromisoformat)
    databento_parser.add_argument("--stype-in", default="parent")
    databento_parser.add_argument("--output", required=True, type=Path)
    normalize_parser = data_sub.add_parser("normalize-databento")
    normalize_parser.add_argument("--input", required=True, type=Path)
    normalize_parser.add_argument("--instrument-map", required=True, type=Path)
    normalize_parser.add_argument("--sessions", required=True, type=Path)
    normalize_parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--registry-path", type=Path, default=default_registry_path())
    args = parser.parse_args()
    if args.area == "registry" and args.command == "init":
        from es_research.registry.repository import DuckDBExperimentRegistry

        DuckDBExperimentRegistry(args.registry_path).initialize()
        print(f"Initialized registry at {args.registry_path}")
        return
    if args.area == "demo" and args.command == "reproducibility":
        values = run_reproducibility_demo(args.registry_path)
        print("Reproducibility demonstration succeeded with matching deterministic values:")
        for key, value in values.items():
            print(f"{key}={value}")
        return
    if args.area == "demo" and args.command == "synthetic-pipeline":
        result = run_synthetic_pipeline(args.output_dir)
        print("Synthetic pipeline demonstration succeeded with deterministic values:")
        print(f"manifest_hash={result.manifest_hash}")
        print(f"normalized_rows_hash={result.normalized_rows_hash}")
        print(f"bars_hash={result.bars_hash}")
        print(f"parquet_sha256={result.parquet_sha256}")
        print(f"report_hash={result.report_hash}")
        print(f"row_count={result.row_count}")
        print(f"bar_count={result.bar_count}")
        print(f"parquet_path={result.parquet_path}")
        print(f"report_path={result.report_path}")
        return
    if args.area == "data" and args.command == "ingest-databento":
        api_key = os.getenv("DATABENTO_API_KEY")
        if not api_key:
            parser.error("DATABENTO_API_KEY must be set for Databento ingestion")
        import databento as db

        from es_research.ingestion.databento import DatabentoRequest, ingest_databento_dbn

        request = DatabentoRequest(
            dataset=args.dataset,
            schema=args.schema,
            symbols=tuple(args.symbols),
            start=args.start,
            end=args.end,
            stype_in=args.stype_in,
        )
        artifact = ingest_databento_dbn(db.Historical(api_key), request, args.output)
        print(f"data_path={artifact.data_path}")
        print(f"metadata_path={artifact.metadata_path}")
        print(f"sha256={artifact.sha256}")
        print(f"byte_count={artifact.byte_count}")
        return
    if args.area == "data" and args.command == "normalize-databento":
        from es_research.configuration.reference_data import (
            load_instrument_map,
            load_session_calendars,
        )
        from es_research.pipeline.databento import run_databento_pipeline

        instrument_map, instrument_map_hash = load_instrument_map(args.instrument_map)
        sessions, session_calendar_hash = load_session_calendars(args.sessions)
        databento_result = run_databento_pipeline(
            args.input,
            args.output_dir,
            symbol_by_instrument=instrument_map,
            sessions=sessions,
            instrument_map_hash=instrument_map_hash,
            session_calendar_hash=session_calendar_hash,
        )
        print(f"bronze_sha256={databento_result.bronze_sha256}")
        print(f"silver_rows_hash={databento_result.silver_rows_hash}")
        print(f"bars_hash={databento_result.bars_hash}")
        print(f"row_count={databento_result.row_count}")
        print(f"bar_count={databento_result.bar_count}")
        print(f"silver_path={databento_result.silver_path}")
        print(f"report_path={databento_result.report_path}")
        return
    parser.error("unknown command")


if __name__ == "__main__":
    main()
