from __future__ import annotations

import argparse
import os
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
    demo_sub.add_parser("synthetic-pipeline")
    parser.add_argument("--registry-path", type=Path, default=default_registry_path())
    args = parser.parse_args()
    if args.area == "registry" and args.command == "init":
        try:
            from es_research.registry.repository import DuckDBExperimentRegistry
        except ModuleNotFoundError as exc:
            parser.exit(status=1, message=f"error: {exc}\n")

        DuckDBExperimentRegistry(args.registry_path).initialize()
        print(f"Initialized registry at {args.registry_path}")
        return
    if args.area == "demo" and args.command == "reproducibility":
        try:
            values = run_reproducibility_demo(args.registry_path)
        except ModuleNotFoundError as exc:
            parser.exit(status=1, message=f"error: {exc}\n")
        print("Reproducibility demonstration succeeded with matching deterministic values:")
        for key, value in values.items():
            print(f"{key}={value}")
        return
    if args.area == "demo" and args.command == "synthetic-pipeline":
        try:
            result = run_synthetic_pipeline(Path("data/registry/synthetic-demo"))
        except ModuleNotFoundError as exc:
            parser.exit(status=1, message=f"error: {exc}\n")
        print("Synthetic pipeline demonstration succeeded with deterministic hashes:")
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
    parser.error("unknown command")


if __name__ == "__main__":
    main()
