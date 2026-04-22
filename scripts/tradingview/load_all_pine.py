#!/usr/bin/env python3
"""
JARVIS Pine Script loader helper.

The TradingView MCP server's internal Pine compiler has two known parser bugs
that we must work around whenever we inject scripts via `pine_set_source`:

  1. The `color.*` namespace is unresolvable — `color.new(color.cyan, 20)`
     fails with "Undeclared identifier 'color'" even in a 4-line test case.
  2. Multi-line ternary/additive expressions fail with "end of line without
     line continuation".
  3. Function definitions inside `if` blocks are rejected.

This CLI pre-flights every `JARVIS_*.pine` file under
`scripts/tradingview/pine/` (excluding the already-loaded master
`JARVIS_MCP_Manifest.pine`) and optionally rewrites the color-namespace
patterns to 8-digit hex literals. The ternary and function-hoist warnings
are reported but NOT auto-fixed (too risky without case-by-case review).

Examples
--------
    python scripts/tradingview/load_all_pine.py --list
    python scripts/tradingview/load_all_pine.py --check
    python scripts/tradingview/load_all_pine.py --fix --dry-run
    python scripts/tradingview/load_all_pine.py --fix

The script does NOT touch TradingView directly — actual chart loading must
be driven by Claude Code's MCP tools (`pine_set_source` + `pine_smart_compile`
+ click "Add to chart"). Use `--generate-load-plan` to emit a JSON plan that
a follow-up session can iterate through.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────

PINE_DIR = Path(__file__).resolve().parent / "pine"
EXCLUDE = {"JARVIS_MCP_Manifest.pine"}  # already loaded on the chart

# Canonical color-namespace → hex replacements.
# Values chosen to match Pine defaults closely enough for visual parity.
COLOR_REPLACEMENTS: Dict[str, str] = {
    "color.new(color.cyan, 20)": "#00FFFFCC",
    "color.new(color.cyan, 0)": "#00FFFFFF",
    "color.new(color.teal, 50)": "#00808080",
    "color.new(color.blue, 60)": "#2196F366",
    "color.new(color.red, 60)": "#FF525266",
    "color.new(color.red, 0)": "#FF5252FF",
    "color.new(color.white, 15)": "#FFFFFFD9",
    "color.new(color.white, 0)": "#FFFFFFFF",
    "color.new(color.gray, 60)": "#787B8666",
    "color.new(color.gray, 50)": "#787B8680",
    "color.new(color.gray, 20)": "#787B86CC",
    "color.new(color.navy, 20)": "#000080CC",
    "color.new(color.black, 70)": "#0000004D",
    "color.new(color.black, 80)": "#00000033",
    "color.new(color.lime, 0)": "#00E676FF",
    "color.new(color.yellow, 0)": "#FFEB3BFF",
    "color.new(color.orange, 0)": "#FF9800FF",
    "color.cyan": "#00FFFF",
    "color.teal": "#008080",
    "color.blue": "#2196F3",
    "color.red": "#FF5252",
    "color.white": "#FFFFFF",
    "color.gray": "#787B86",
    "color.navy": "#000080",
    "color.black": "#000000",
    "color.lime": "#00E676",
    "color.yellow": "#FFEB3B",
    "color.orange": "#FF9800",
    "color.green": "#4CAF50",
    "color.purple": "#9C27B0",
    "color.fuchsia": "#E040FB",
    "color.silver": "#B0BEC5",
    "color.maroon": "#880E4F",
    "color.olive": "#827717",
    "color.aqua": "#00BCD4",
}

# Compile a single regex to find ANY lingering `color.xxx` reference
# for reporting purposes.
COLOR_NS_REGEX = re.compile(r"\bcolor\.[a-zA-Z_][a-zA-Z0-9_]*")

# Multi-line ternary: a line that ends with `?` or `:` (not inside a string)
TERNARY_TAIL_REGEX = re.compile(r"[?:]\s*$")

# Function-in-if: `_xxx(args) =>` indented after an `if ...:` line
FN_IN_IF_REGEX = re.compile(r"^\s{4,}\w+\([^)]*\)\s*=>")


@dataclass
class ScriptReport:
    name: str
    path: Path
    size_bytes: int
    line_count: int
    color_hits: int = 0
    ternary_warnings: list[int] = field(default_factory=list)
    fn_in_if_warnings: list[int] = field(default_factory=list)
    clean: bool = True


# ──────────────────────────────────────────────────────────────────────────
# Scanning
# ──────────────────────────────────────────────────────────────────────────


def discover() -> list[Path]:
    if not PINE_DIR.exists():
        print(f"ERROR: Pine dir not found: {PINE_DIR}", file=sys.stderr)
        sys.exit(1)
    files = sorted(p for p in PINE_DIR.glob("JARVIS_*.pine") if p.name not in EXCLUDE)
    return files


def strip_comments(line: str) -> str:
    """Return the line with any `//` comment trailing removed."""
    # This is naive — doesn't handle `//` inside strings — but close enough
    # for our pattern-matching needs.
    idx = line.find("//")
    return line[:idx] if idx != -1 else line


def scan_one(path: Path) -> ScriptReport:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    report = ScriptReport(
        name=path.name,
        path=path,
        size_bytes=len(text.encode("utf-8")),
        line_count=len(lines),
    )

    in_if_block = False
    if_indent = 0
    for idx, raw in enumerate(lines, 1):
        code = strip_comments(raw)

        # color.* namespace hit
        if COLOR_NS_REGEX.search(code):
            report.color_hits += 1

        # multi-line ternary continuation
        stripped = code.rstrip()
        if stripped.endswith("?") or (stripped.endswith(":") and "?" in stripped):
            report.ternary_warnings.append(idx)

        # crude if-block tracking for function-in-if detection
        m = re.match(r"^(\s*)if\s+", raw)
        if m:
            in_if_block = True
            if_indent = len(m.group(1))
            continue
        if in_if_block:
            indent = len(raw) - len(raw.lstrip())
            if raw.strip() and indent <= if_indent:
                in_if_block = False
            elif FN_IN_IF_REGEX.match(raw):
                report.fn_in_if_warnings.append(idx)

    report.clean = (
        report.color_hits == 0
        and not report.ternary_warnings
        and not report.fn_in_if_warnings
    )
    return report


# ──────────────────────────────────────────────────────────────────────────
# Fixing
# ──────────────────────────────────────────────────────────────────────────


def apply_color_fixes(text: str) -> tuple[str, int]:
    """Replace every known color.* pattern with its hex literal. Returns
    (new_text, replacements_made)."""
    count = 0
    new_text = text
    # Sort by length DESC so `color.new(color.cyan, 20)` is replaced before
    # the bare `color.cyan` fallback.
    for needle in sorted(COLOR_REPLACEMENTS.keys(), key=len, reverse=True):
        if needle in new_text:
            occurrences = new_text.count(needle)
            new_text = new_text.replace(needle, COLOR_REPLACEMENTS[needle])
            count += occurrences
    return new_text, count


def fix_one(path: Path, dry_run: bool) -> tuple[int, bool]:
    """Apply safe color fixes to `path`. Returns (replacements, wrote_file)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    new_text, count = apply_color_fixes(text)
    if count == 0 or new_text == text:
        return 0, False
    if dry_run:
        return count, False
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(text, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    return count, True


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────


def cmd_list(_args: argparse.Namespace) -> int:
    files = discover()
    print(f"Found {len(files)} JARVIS Pine scripts in {PINE_DIR}:")
    for f in files:
        print(f"  {f.name:45} {f.stat().st_size:>7} bytes")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    files = discover()
    reports = [scan_one(f) for f in files]
    clean = sum(1 for r in reports if r.clean)
    total_color = sum(r.color_hits for r in reports)
    total_tern = sum(len(r.ternary_warnings) for r in reports)
    total_fnif = sum(len(r.fn_in_if_warnings) for r in reports)

    print(f"Scanned {len(reports)} files ({clean} clean, {len(reports)-clean} with issues)")
    print(f"Total issues — color hits: {total_color}, ternary warnings: {total_tern}, fn-in-if: {total_fnif}")
    print()

    for r in reports:
        status = "OK " if r.clean else "FIX"
        print(f"[{status}] {r.name:45} lines={r.line_count} color={r.color_hits} tern={len(r.ternary_warnings)} fnif={len(r.fn_in_if_warnings)}")
        if r.ternary_warnings[:3]:
            print(f"       ternary lines: {r.ternary_warnings[:5]}{'...' if len(r.ternary_warnings)>5 else ''}")
        if r.fn_in_if_warnings[:3]:
            print(f"       fn-in-if lines: {r.fn_in_if_warnings[:5]}{'...' if len(r.fn_in_if_warnings)>5 else ''}")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    files = discover()
    total = 0
    wrote = 0
    for f in files:
        count, did_write = fix_one(f, dry_run=args.dry_run)
        total += count
        if did_write:
            wrote += 1
            print(f"  [WROTE] {f.name}: {count} color fixes")
        elif count:
            print(f"  [DRY  ] {f.name}: would apply {count} color fixes")
        else:
            print(f"  [SKIP ] {f.name}: clean")
    mode = "dry-run" if args.dry_run else "applied"
    print(f"\n{mode.upper()}: {total} replacements across {wrote if not args.dry_run else sum(1 for f in files if apply_color_fixes(f.read_text(encoding='utf-8'))[1]>0)} files")
    if not args.dry_run and wrote:
        print("Note: original files backed up as *.pine.bak")
    print("\nReminder: the TV parser ALSO rejects multi-line ternaries and")
    print("function-in-if blocks. These require manual fixes — run --check")
    print("to see which files still need them.")
    return 0


def cmd_generate_load_plan(_args: argparse.Namespace) -> int:
    files = discover()
    reports = [scan_one(f) for f in files]
    plan = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "pine_dir": str(PINE_DIR),
        "total_scripts": len(reports),
        "load_order": [
            {
                "name": r.name,
                "path": str(r.path),
                "size_bytes": r.size_bytes,
                "line_count": r.line_count,
                "clean": r.clean,
                "needs_fixes": {
                    "color_hits": r.color_hits,
                    "ternary_warnings": r.ternary_warnings,
                    "fn_in_if_warnings": r.fn_in_if_warnings,
                },
                "mcp_steps": [
                    f"pine_new(type='indicator')",
                    f"# open {r.path.name} and read its text",
                    f"pine_set_source(source=<file content>)",
                    f"pine_smart_compile()",
                    f"ui_click(by='text', value='Add to chart')",
                ],
            }
            for r in reports
        ],
    }
    print(json.dumps(plan, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="JARVIS Pine script loader helper")
    sub = p.add_subparsers(dest="cmd")

    # Shortcut flags also supported
    p.add_argument("--list", action="store_true", help="List discovered files")
    p.add_argument("--check", action="store_true", help="Scan for parser issues")
    p.add_argument("--fix", action="store_true", help="Apply safe color fixes")
    p.add_argument("--dry-run", action="store_true", help="With --fix, do not touch files")
    p.add_argument("--generate-load-plan", action="store_true", help="Emit JSON plan to stdout")

    args = p.parse_args()

    if args.list:
        return cmd_list(args)
    if args.check:
        return cmd_check(args)
    if args.fix:
        return cmd_fix(args)
    if args.generate_load_plan:
        return cmd_generate_load_plan(args)

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
