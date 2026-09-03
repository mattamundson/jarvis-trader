#!/usr/bin/env python3
"""Audit legacy instrument multiplier authorities without importing engine code.

B-01 uses this as migration evidence. The scanner parses source AST only, so it
cannot trigger config loading, broker connections, or runtime side effects.
Known contradictions are reported, not silently normalized.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "position_sizing": (REPO_ROOT / "engine" / "utils" / "position_sizing.py", "INSTRUMENT_MULTIPLIERS"),
    "portfolio_tracker": (REPO_ROOT / "engine" / "portfolio" / "tracker.py", "INSTRUMENT_MULTIPLIERS"),
    "backtest_contract_specs": (REPO_ROOT / "engine" / "backtest" / "contract_specs.py", "CONTRACT_SPECS"),
}
PROVIDER_ALIASES = {
    "MES=F": "MES",
    "NQ=F": "NQ",
    "CL=F": "CL",
    "GC=F": "GC",
}


def _literal_number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    return None


def _find_assignment(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                return node.value
    raise ValueError(f"assignment {name!r} not found")


def _extract_plain_multiplier_dict(path: Path, variable: str) -> dict[str, float]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _find_assignment(tree, variable)
    if not isinstance(value, ast.Dict):
        raise ValueError(f"{path}: {variable} must be a dict literal")
    result: dict[str, float] = {}
    for key_node, value_node in zip(value.keys, value.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        number = _literal_number(value_node)
        if number is not None:
            result[key_node.value.upper()] = number
    return result


def _extract_contract_specs(path: Path, variable: str) -> dict[str, float]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _find_assignment(tree, variable)
    if not isinstance(value, ast.Dict):
        raise ValueError(f"{path}: {variable} must be a dict literal")
    result: dict[str, float] = {}
    for key_node, value_node in zip(value.keys, value.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        if not isinstance(value_node, ast.Call):
            continue
        multiplier: float | None = None
        for keyword in value_node.keywords:
            if keyword.arg == "multiplier":
                multiplier = _literal_number(keyword.value)
                break
        if multiplier is not None:
            result[key_node.value.upper()] = multiplier
    return result


def load_sources(repo_root: Path = REPO_ROOT) -> dict[str, dict[str, float]]:
    resolved = {
        "position_sizing": (repo_root / "engine" / "utils" / "position_sizing.py", "INSTRUMENT_MULTIPLIERS"),
        "portfolio_tracker": (repo_root / "engine" / "portfolio" / "tracker.py", "INSTRUMENT_MULTIPLIERS"),
        "backtest_contract_specs": (repo_root / "engine" / "backtest" / "contract_specs.py", "CONTRACT_SPECS"),
    }
    return {
        "position_sizing": _extract_plain_multiplier_dict(*resolved["position_sizing"]),
        "portfolio_tracker": _extract_plain_multiplier_dict(*resolved["portfolio_tracker"]),
        "backtest_contract_specs": _extract_contract_specs(*resolved["backtest_contract_specs"]),
    }


def build_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    sources = load_sources(repo_root)
    all_symbols = sorted(set().union(*(set(values) for values in sources.values())))
    multiplier_mismatches: list[dict[str, Any]] = []
    for symbol in all_symbols:
        observed = {name: values[symbol] for name, values in sources.items() if symbol in values}
        if len(observed) >= 2 and len(set(observed.values())) > 1:
            multiplier_mismatches.append({"symbol": symbol, "observed": observed})

    alias_findings: list[dict[str, Any]] = []
    position = sources["position_sizing"]
    for alias, canonical in PROVIDER_ALIASES.items():
        if alias not in position:
            continue
        canonical_values = {
            source: values[canonical]
            for source, values in sources.items()
            if canonical in values
        }
        alias_multiplier = position[alias]
        alias_findings.append(
            {
                "alias": alias,
                "canonical": canonical,
                "alias_multiplier": alias_multiplier,
                "canonical_values": canonical_values,
                "multiplier_mismatch": any(
                    value != alias_multiplier for value in canonical_values.values()
                ),
                "requires_disposition": True,
            }
        )

    presence = {
        symbol: sorted(name for name, values in sources.items() if symbol in values)
        for symbol in all_symbols
    }
    incomplete_coverage = [
        {"symbol": symbol, "present_in": names}
        for symbol, names in presence.items()
        if len(names) != len(sources)
    ]
    alias_mismatches = [row for row in alias_findings if row["multiplier_mismatch"]]

    return {
        "audit": "JARVIS_B01_LEGACY_INSTRUMENT_METADATA",
        "schema_version": 1,
        "runtime_imports_used": False,
        "source_count": len(sources),
        "sources": sources,
        "multiplier_mismatches": multiplier_mismatches,
        "provider_aliases": alias_findings,
        "alias_multiplier_mismatches": alias_mismatches,
        "incomplete_coverage": incomplete_coverage,
        "migration_authorized": False,
        "summary": {
            "symbol_count": len(all_symbols),
            "cross_source_multiplier_mismatches": len(multiplier_mismatches),
            "provider_aliases_requiring_disposition": len(alias_findings),
            "alias_multiplier_mismatches": len(alias_mismatches),
            "symbols_without_three_source_coverage": len(incomplete_coverage),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit legacy JARVIS instrument metadata.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when contradictions remain; default audit mode reports debt and exits 0.",
    )
    args = parser.parse_args(argv)
    try:
        report = build_audit(args.repo_root.resolve())
    except (OSError, SyntaxError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print("B-01 legacy instrument metadata audit")
        for key, value in summary.items():
            print(f"{key}: {value}")
        for row in report["alias_multiplier_mismatches"]:
            print(
                f"[CONTRADICTION] {row['alias']}={row['alias_multiplier']} vs "
                f"{row['canonical']}={row['canonical_values']}"
            )
        print("Migration authorized: NEVER by this audit.")

    has_debt = bool(report["multiplier_mismatches"] or report["incomplete_coverage"])
    return 2 if args.strict and has_debt else 0


if __name__ == "__main__":
    sys.exit(main())
