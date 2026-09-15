from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Callable, Sequence

from morning_alpha.reporting import render_morning_report
from morning_alpha.service import MorningAlphaService, ScanStatus


ServiceFactory = Callable[[argparse.Namespace], MorningAlphaService]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="morning-alpha")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--as-of", required=True)
    scan.add_argument("--provider", default="alpaca", choices=("alpaca", "historical", "fake"))
    scan.add_argument("--symbols", required=True, help="comma-separated symbols")
    scan.add_argument("--json", action="store_true", dest="json_output")

    audit = sub.add_parser("audit")
    audit.add_argument("--session", required=True)

    lab = sub.add_parser("research-trigger-lab")
    lab.add_argument("--strategy", required=True)

    return parser


def _parse_as_of(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    ts = datetime.fromisoformat(normalized)
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("--as-of must include timezone/offset")
    return ts


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: ServiceFactory | None = None,
    audit_handler: Callable[[str], str] | None = None,
    trigger_lab_handler: Callable[[str], str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        if service_factory is None:
            raise RuntimeError("scan requires a configured service_factory")
        service = service_factory(args)
        as_of = _parse_as_of(args.as_of)
        symbols = tuple(x.strip().upper() for x in args.symbols.split(",") if x.strip())
        result = service.scan(as_of=as_of, symbols=symbols)
        if args.json_output:
            print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        elif result.status is ScanStatus.NO_TRADE:
            print("NO_TRADE")
        else:
            print(render_morning_report(result), end="")
        return 0

    if args.command == "audit":
        if audit_handler is None:
            raise RuntimeError("audit requires an audit_handler")
        print(audit_handler(args.session))
        return 0

    if args.command == "research-trigger-lab":
        if trigger_lab_handler is None:
            raise RuntimeError("research-trigger-lab requires a trigger_lab_handler")
        print(trigger_lab_handler(args.strategy))
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
