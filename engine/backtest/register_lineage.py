"""Operator CLI to register decision lineages (P3).

Registering a decision lineage is a safety-critical operator action: it asserts
"this config_hash is the SAME edge hypothesis as that one" *before* a forward
window is counted. Hand-editing ``decision_registry.json`` is error-prone and --
worse -- it makes edge-laundering easy: silently fold a config_hash that already
prints money into a pre-registered lineage and inherit its forward record.

This CLI makes registration a single validated command. The honesty guard is
``verify_registry``: before any write, the prospective registry is verified, and
if a config_hash is already claimed by a DIFFERENT lineage (or any other contract
violation), the write is ABORTED with a non-zero exit and nothing is written.

Subcommands:
* ``list``                       -- show lineages + verify status + active count
* ``show-current --symbol SYM``  -- the config_hash currently running
* ``register --id ID --symbol SYM ...`` -- create/extend a lineage (validated)

Run from ``engine/`` (the path shim below mirrors the test files).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

os.environ.setdefault("API_KEY", "x")

# Allow imports of ``agents.*`` / ``backtest.*`` / ``config.*`` when run from engine/.
_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from agents.decision_identity import (  # noqa: E402
    compute_config_fingerprint,
    current_decision_identity,
)
from backtest.decision_registry import (  # noqa: E402
    _DEFAULT_REGISTRY,
    get_active_lineages,
    load_registry,
    verify_registry,
)


def _print_verify(registry: dict) -> list[str]:
    """Print the verify status; return the problems list."""
    problems = verify_registry(registry)
    if problems:
        print("registry problems:")
        for p in problems:
            print(f"  - {p}")
    else:
        print("registry OK")
    return problems


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    lineages = registry.get("lineages", [])
    if not lineages:
        print("(no lineages registered)")
    for lin in lineages:
        hashes = lin.get("member_config_hashes") or []
        symbols = lin.get("symbols") or []
        print(
            f"- {lin.get('id')}  [{lin.get('status')}]  "
            f"{len(hashes)} hash(es)  symbols={','.join(symbols) or '-'}"
        )
    print()
    _print_verify(registry)
    active = get_active_lineages(registry)
    print(f"active (forward_testing) lineages: {len(active)}")
    return 0


def cmd_show_current(args: argparse.Namespace) -> int:
    ident = current_decision_identity(args.symbol)
    chash = ident.get("config_hash")
    print(f"symbol:           {ident.get('symbol')}")
    print(f"config_hash:      {chash}")
    if chash:
        print(f"config_hash[:8]:  {chash[:8]}")
    print(f"lineage:          {ident.get('lineage')}")
    print(f"pipeline_version: {ident.get('pipeline_version')}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    if args.add_current_hash:
        chash = compute_config_fingerprint()["config_hash"]
    elif args.hash:
        chash = args.hash
    else:
        print(
            "error: provide --hash HEX or --add-current-hash",
            file=sys.stderr,
        )
        return 2

    sym = (args.symbol or "?").upper()
    registry = load_registry(args.registry)
    lineages = registry.setdefault("lineages", [])

    existing = next((lin for lin in lineages if lin.get("id") == args.id), None)
    if existing is not None:
        hashes = existing.setdefault("member_config_hashes", [])
        if chash not in hashes:
            hashes.append(chash)
        symbols = existing.setdefault("symbols", [])
        if sym not in symbols:
            symbols.append(sym)
        if args.note:
            existing["note"] = args.note
        action = "extended"
    else:
        lineages.append(
            {
                "id": args.id,
                "status": args.status,
                "member_config_hashes": [chash],
                "symbols": [sym],
                "registered_at": datetime.date.today().isoformat(),
                "note": args.note or "",
            }
        )
        action = "created"

    # Honesty guard: verify the PROSPECTIVE registry before writing anything.
    problems = verify_registry(registry)
    if problems:
        print("ABORT: prospective registry failed verification:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("nothing written.", file=sys.stderr)
        return 1

    print(f"would {action} lineage {args.id!r} with config_hash {chash[:8]} ({sym})")

    if args.dry_run:
        print("--dry-run: nothing written.")
        _print_verify(registry)
        return 0

    path = args.registry or _DEFAULT_REGISTRY
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2)
        fh.write("\n")
    print(f"{action} lineage {args.id!r}; wrote {path}")
    _print_verify(registry)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="register_lineage",
        description="Operator CLI to register decision lineages (P3).",
    )
    parser.add_argument(
        "--registry",
        default=None,
        help="path to decision_registry.json (default: module default)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list lineages + verify status")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show-current", help="show currently-running config_hash")
    p_show.add_argument("--symbol", required=True)
    p_show.set_defaults(func=cmd_show_current)

    p_reg = sub.add_parser("register", help="create or extend a lineage")
    p_reg.add_argument("--id", required=True, help="lineage id")
    p_reg.add_argument("--symbol", required=True)
    p_reg.add_argument("--status", default="forward_testing")
    p_reg.add_argument(
        "--add-current-hash",
        action="store_true",
        help="use the running config_hash",
    )
    p_reg.add_argument("--hash", default=None, help="explicit config_hash hex")
    p_reg.add_argument("--note", default=None)
    p_reg.add_argument("--dry-run", action="store_true")
    p_reg.set_defaults(func=cmd_register)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
