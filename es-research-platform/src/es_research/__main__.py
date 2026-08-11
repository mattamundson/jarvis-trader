from __future__ import annotations

import argparse
import os
from pathlib import Path

from es_research.demo import run_reproducibility_demo


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
    parser.error("unknown command")


if __name__ == "__main__":
    main()
