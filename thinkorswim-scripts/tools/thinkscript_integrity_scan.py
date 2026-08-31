#!/usr/bin/env python3
"""Static source-integrity scanner for JARVIS ThinkScript research files.

The scanner flags constructs that require human point-in-time/repaint review. A
finding is not proof of leakage or of alpha; it is a precheck for causal review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

NEGATIVE_INDEX_RE = re.compile(r"\[\s*-\s*(\d+)\s*\]")
FUTURE_TIME_RE = re.compile(
    r"(?:GetTime|GetMonth|GetYear)\s*\(\s*\)\s*\[\s*-\s*\d+\s*\]", re.I
)
HARD_DATE_RE = re.compile(r"\b20\d{6}\b")
EXTERNAL_SYMBOL_RE = re.compile(
    r'(?:close|high|low|open)\s*\(\s*["\']([^"\']+)["\']\s*\)', re.I
)


def strip_comments(text: str) -> str:
    """Strip ThinkScript # comments before static pattern scanning."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


@dataclass
class Finding:
    file: str
    sha256: str
    lines: int
    negative_index_count: int
    negative_index_values: list[int]
    future_calendar_reference_count: int
    highest_all_count: int
    lowest_all_count: int
    inertia_all_count: int
    profile_primitive_count: int
    hardcoded_date_count: int
    external_symbols: list[str]
    pine_style_ta_namespace: bool
    requires_manual_causal_review: bool
    notes: list[str]


def scan_file(path: Path) -> Finding:
    raw = path.read_text(errors="ignore")
    code = strip_comments(raw)

    neg = [int(x) for x in NEGATIVE_INDEX_RE.findall(code)]
    future_calendar = len(FUTURE_TIME_RE.findall(code))
    highest = len(re.findall(r"\bHighestAll\s*\(", code, re.I))
    lowest = len(re.findall(r"\bLowestAll\s*\(", code, re.I))
    inertia = len(re.findall(r"\bInertiaAll\s*\(", code, re.I))
    profiles = len(re.findall(r"\b(?:TimeProfile|VolumeProfile)\s*\(", code, re.I))
    hard_dates = len(HARD_DATE_RE.findall(code))
    externals = sorted(set(EXTERNAL_SYMBOL_RE.findall(code)))
    pine = bool(re.search(r"\bta\.", code))

    notes: list[str] = []
    if neg:
        notes.append(
            "Negative bar indexes present; determine whether each is display-only or future-data dependent."
        )
    if future_calendar:
        notes.append(
            "Future calendar/bar references present; replace with exchange-calendar logic for production."
        )
    if highest or lowest:
        notes.append(
            "Chart-global HighestAll/LowestAll present; verify they are not used in historical predictive state."
        )
    if inertia:
        notes.append(
            "InertiaAll present; verify chart-global/full-range mode is not used in production features."
        )
    if profiles:
        notes.append(
            "Profile primitives present; parity depends on profile/session/data-resolution semantics."
        )
    if hard_dates:
        notes.append(
            "Hard-coded dates present; move calendar semantics to a versioned exchange-calendar service."
        )
    if externals:
        notes.append("External-symbol dependencies require timestamp-aligned multi-asset data.")
    if pine:
        notes.append(
            "Pine-style ta.* namespace detected in a ThinkScript source; compile/parity review required."
        )

    causal = bool(neg or future_calendar or highest or lowest or inertia or profiles or hard_dates or pine)

    return Finding(
        file=path.name,
        sha256=hashlib.sha256(raw.encode(errors="ignore")).hexdigest(),
        lines=raw.count("\n") + 1,
        negative_index_count=len(neg),
        negative_index_values=sorted(set(neg)),
        future_calendar_reference_count=future_calendar,
        highest_all_count=highest,
        lowest_all_count=lowest,
        inertia_all_count=inertia,
        profile_primitive_count=profiles,
        hardcoded_date_count=hard_dates,
        external_symbols=externals,
        pine_style_ta_namespace=pine,
        requires_manual_causal_review=causal,
        notes=notes,
    )


def scan_directory(source_dir: Path) -> list[Finding]:
    return [scan_file(path) for path in sorted(source_dir.glob("*.ts"))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()

    payload = [asdict(item) for item in scan_directory(args.source_dir)]
    serialized = json.dumps(payload, indent=2)
    if args.json_path:
        args.json_path.write_text(serialized)
    else:
        print(serialized)


if __name__ == "__main__":
    main()
