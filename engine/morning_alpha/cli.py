from __future__ import annotations

import argparse
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Callable, Sequence

from morning_alpha.reporting import render_morning_report
from morning_alpha.research.acquisition import RESEARCH_ACQUISITION_PLAN
from morning_alpha.research.campaign import (
    ResearchArtifactKind,
    ResearchArtifactReceipt,
    ResearchCampaignSpec,
    build_manifest_from_receipts,
    inspect_research_files,
)
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

    data_check = sub.add_parser("research-data-check")
    data_check.add_argument("--data-root", required=True)
    data_check.add_argument("--json", action="store_true", dest="json_output")

    campaign_plan = sub.add_parser("research-campaign-plan")
    campaign_plan.add_argument("--json", action="store_true", dest="json_output")

    source_plan = sub.add_parser("research-source-plan")
    source_plan.add_argument("--json", action="store_true", dest="json_output")

    receipt = sub.add_parser("research-receipt-create")
    receipt.add_argument("--data-root", required=True)
    receipt.add_argument("--kind", required=True, choices=tuple(kind.value for kind in ResearchArtifactKind))
    receipt.add_argument("--path", required=True)
    receipt.add_argument("--provider", required=True)
    receipt.add_argument("--row-count", required=True, type=int)
    receipt.add_argument("--symbol-count", required=True, type=int)
    receipt.add_argument("--earliest")
    receipt.add_argument("--latest")
    receipt.add_argument("--point-in-time", action="store_true")
    receipt.add_argument("--json", action="store_true", dest="json_output")

    manifest_build = sub.add_parser("research-manifest-build")
    manifest_build.add_argument("--data-root", required=True)
    manifest_build.add_argument("--json", action="store_true", dest="json_output")

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

    if args.command == "research-data-check":
        report = inspect_research_files(args.data_root)
        if args.json_output:
            print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        else:
            status = "READY" if report.ready else "NOT_READY"
            print(f"{status}: {args.data_root}")
            if report.reasons:
                print("Reasons: " + ", ".join(report.reasons))
        return 0 if report.ready else 2

    if args.command == "research-campaign-plan":
        spec = ResearchCampaignSpec()
        if args.json_output:
            print(json.dumps(spec.model_dump(mode="json"), sort_keys=True))
        else:
            print(spec.model_dump_json(indent=2))
        return 0

    if args.command == "research-source-plan":
        plan = RESEARCH_ACQUISITION_PLAN
        if args.json_output:
            print(json.dumps(plan.model_dump(mode="json"), sort_keys=True))
        else:
            print(plan.model_dump_json(indent=2))
        return 0

    if args.command == "research-receipt-create":
        root = Path(args.data_root)
        relative = Path(args.path)
        if relative.is_absolute() or ".." in relative.parts:
            payload = {"error": "ARTIFACT_PATH_INVALID", "path": args.path}
            print(json.dumps(payload, sort_keys=True) if args.json_output else payload["error"])
            return 2
        artifact = root / relative
        if not artifact.is_file():
            payload = {"error": "ARTIFACT_FILE_MISSING", "path": args.path}
            print(json.dumps(payload, sort_keys=True) if args.json_output else payload["error"])
            return 2
        receipt = ResearchArtifactReceipt(
            kind=ResearchArtifactKind(args.kind),
            path=relative.as_posix(),
            sha256=sha256(artifact.read_bytes()).hexdigest(),
            provider=args.provider,
            row_count=args.row_count,
            symbol_count=args.symbol_count,
            earliest_timestamp=_parse_as_of(args.earliest) if args.earliest else None,
            latest_timestamp=_parse_as_of(args.latest) if args.latest else None,
            point_in_time=args.point_in_time,
        )
        receipts_dir = root / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipts_dir / f"{receipt.kind.value}.json"
        receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
        if args.json_output:
            print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
        else:
            print(receipt_path)
        return 0

    if args.command == "research-manifest-build":
        root = Path(args.data_root)
        receipt_files = sorted((root / "receipts").glob("*.json"))
        if not receipt_files:
            payload = {"error": "NO_RECEIPTS"}
            print(json.dumps(payload, sort_keys=True) if args.json_output else payload["error"])
            return 2
        receipts = [
            ResearchArtifactReceipt.model_validate_json(path.read_text(encoding="utf-8"))
            for path in receipt_files
        ]
        manifest = build_manifest_from_receipts(receipts, generated_at=datetime.now().astimezone())
        manifest_path = root / "research_manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        if args.json_output:
            print(json.dumps(manifest.model_dump(mode="json"), sort_keys=True))
        else:
            print(manifest_path)
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
