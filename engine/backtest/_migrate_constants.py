"""
One-shot migration script: replaces local constant definitions in runner files
with imports from _constants.py.

Run from engine/ directory:
    python backtest/_migrate_constants.py

Removes these local lines:
    GATE_FIXED_PARAMS_MIN_PF = 1.20[  ...]
    GATE_WFO_CONSISTENCY_VALUES = ["MODERATE", "STRONG"][  ...]
    COST_TIER_ORDER = ["optimistic", "realistic", "pessimistic", "catastrophic"]

Adds this import near the existing _gate_v2_helpers import block:
    from backtest._constants import (  # noqa: E402
        COST_TIER_ORDER,
        GATE_FIXED_PARAMS_MIN_PF,
        GATE_WFO_CONSISTENCY_VALUES,
    )

Files that use GATE_WFO_CONSISTENCY (string, not list) are left unchanged.
Files whose COST_TIER_ORDER is already imported from _gate_v2_helpers are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKTEST_DIR = Path(__file__).parent

# Patterns for lines we want to remove
_REMOVE_PATTERNS = [
    # GATE_FIXED_PARAMS_MIN_PF = 1.20  # optional comment
    re.compile(r"^GATE_FIXED_PARAMS_MIN_PF\s*=\s*1\.20\b.*\n", re.MULTILINE),
    # GATE_WFO_CONSISTENCY_VALUES = ["MODERATE", "STRONG"]  # optional comment
    re.compile(
        r'^GATE_WFO_CONSISTENCY_VALUES\s*=\s*\["MODERATE",\s*"STRONG"\].*\n',
        re.MULTILINE,
    ),
    # COST_TIER_ORDER = ["optimistic", "realistic", "pessimistic", "catastrophic"]
    re.compile(
        r'^COST_TIER_ORDER\s*=\s*\["optimistic",\s*"realistic",\s*"pessimistic",\s*"catastrophic"\]\n',
        re.MULTILINE,
    ),
]

_CONSTANTS_IMPORT = (
    "from backtest._constants import (  # noqa: E402\n"
    "    COST_TIER_ORDER,\n"
    "    GATE_FIXED_PARAMS_MIN_PF,\n"
    "    GATE_WFO_CONSISTENCY_VALUES,\n"
    ")\n"
)

# Anchor: insert the _constants import right before the _gate_v2_helpers import block
_ANCHOR = re.compile(r"^from backtest\._gate_v2_helpers import", re.MULTILINE)


def _should_add_wfo_consistency(content: str) -> bool:
    """Only add GATE_WFO_CONSISTENCY_VALUES import if it was defined locally."""
    return bool(re.search(r"^GATE_WFO_CONSISTENCY_VALUES\s*=", content, re.MULTILINE))


def migrate_file(path: Path) -> tuple[bool, str]:
    """Return (changed, reason)."""
    original = path.read_text(encoding="utf-8")

    # Skip if already imports from _constants
    if "from backtest._constants import" in original:
        return False, "already migrated"

    # Skip if uses string form GATE_WFO_CONSISTENCY (different variable name)
    if re.search(r'^GATE_WFO_CONSISTENCY\s*=\s*"', original, re.MULTILINE):
        return False, "uses string-form GATE_WFO_CONSISTENCY — skipped"

    # Check which constants are present
    has_gate_fixed = bool(re.search(r"^GATE_FIXED_PARAMS_MIN_PF\s*=", original, re.MULTILINE))
    has_wfo_values = _should_add_wfo_consistency(original)
    has_cost_tier = bool(re.search(r"^COST_TIER_ORDER\s*=", original, re.MULTILINE))

    if not (has_gate_fixed or has_wfo_values or has_cost_tier):
        return False, "no target constants found"

    modified = original

    # Remove local definitions
    for pat in _REMOVE_PATTERNS:
        modified = pat.sub("", modified)

    # Build the import block dynamically based on what we found
    imports = sorted(
        filter(
            None,
            [
                "    COST_TIER_ORDER," if has_cost_tier else None,
                "    GATE_FIXED_PARAMS_MIN_PF," if has_gate_fixed else None,
                "    GATE_WFO_CONSISTENCY_VALUES," if has_wfo_values else None,
            ],
        )
    )
    import_block = "from backtest._constants import (  # noqa: E402\n"
    import_block += "\n".join(imports) + "\n"
    import_block += ")\n"

    # Insert before the _gate_v2_helpers import if present
    anchor_match = _ANCHOR.search(modified)
    if anchor_match:
        pos = anchor_match.start()
        modified = modified[:pos] + import_block + modified[pos:]
    else:
        # Append at end of file as fallback
        modified = modified.rstrip("\n") + "\n" + import_block

    if modified == original:
        return False, "no changes after substitution"

    path.write_text(modified, encoding="utf-8")
    return True, "migrated"


def main() -> None:
    runner_files = sorted(BACKTEST_DIR.glob("run_*.py"))
    changed, skipped = 0, 0
    for f in runner_files:
        ok, reason = migrate_file(f)
        status = "CHANGED" if ok else "skip"
        print(f"  {status:7s}  {f.name}: {reason}")
        if ok:
            changed += 1
        else:
            skipped += 1
    print(f"\nTotal: {changed} changed, {skipped} skipped out of {len(runner_files)} runners")


if __name__ == "__main__":
    main()
