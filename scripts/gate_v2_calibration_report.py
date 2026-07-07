"""CLI for the Bayesian gate-v2 threshold calibrator.

Usage
-----
    engine/.venv/Scripts/python scripts/gate_v2_calibration_report.py [OPTIONS]

Options
-------
    --days N        Lookback window in calendar days (default: 90)
    --output md     Output format: 'md' (default) or 'json'

Output
------
Markdown:
    - Written to stdout.
    - Also written to
      master-jarvis/second-brain/raw/_session-calibration/gate-v2-<YYYY-MM-DD>.md
      for vault ingestion.

JSON:
    - Written to stdout only (for programmatic consumption).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure engine package is importable when run from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from analytics.gate_v2_calibrator import (
    collect_historical_verdicts,
    diff_vs_current,
    recommended_thresholds,
    render_vault_markdown,
)

_VAULT_OUTPUT_DIR = (
    _REPO_ROOT.parent
    / "master-jarvis"
    / "second-brain"
    / "raw"
    / "_session-calibration"
)


def _build_json_payload(
    rec: dict,
    diff: dict,
    lookback_days: int,
    run_date: str,
) -> dict:
    return {
        "run_date": run_date,
        "lookback_days": lookback_days,
        "sample_size": rec["sample_size"],
        "confidence": rec["confidence"],
        "recommendation_strength": rec["recommendation_strength"],
        "recommended_thresholds": {
            k: v
            for k, v in rec.items()
            if k not in {"sample_size", "confidence", "recommendation_strength"}
        },
        "diff_vs_current": diff,
        "note": "Read-only. Recommendations never auto-applied.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bayesian gate-v2 threshold calibration report (read-only)."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        metavar="N",
        help="Lookback window in calendar days (default: 90)",
    )
    parser.add_argument(
        "--output",
        choices=["md", "json"],
        default="md",
        help="Output format: 'md' (default) or 'json'",
    )
    args = parser.parse_args(argv)

    run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Collect verdicts
    verdicts_df = collect_historical_verdicts(lookback_days=args.days)
    rec = recommended_thresholds(verdicts_df)
    diff = diff_vs_current(rec)

    if args.output == "json":
        payload = _build_json_payload(rec, diff, args.days, run_date)
        print(json.dumps(payload, indent=2))
        return 0

    # Markdown
    md = render_vault_markdown(rec, diff, run_date=run_date)

    # Write to stdout
    print(md)

    # Write to vault (best-effort — don't fail the script if the path is absent)
    vault_file = _VAULT_OUTPUT_DIR / f"gate-v2-{run_date}.md"
    try:
        _VAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        vault_file.write_text(md, encoding="utf-8")
        print(
            f"\n[calibrator] Vault snapshot written to: {vault_file}",
            file=sys.stderr,
        )
    except OSError as exc:
        print(
            f"\n[calibrator] Could not write vault snapshot ({exc}); "
            "stdout output is still valid.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
