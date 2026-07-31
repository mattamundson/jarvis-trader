#!/usr/bin/env python
"""Safety-invariant VALUE guard -- stdlib only, executes NO engine code.

PRB-15: the "Safety-critical config gate" CI job (.github/workflows/
safety-invariant-check.yml) only ever checked for the *presence* of a
`[safety-review]` tag string in the PR body -- it never actually diffed the
live values of the invariants that tag is supposed to certify a human
reviewed. That let the documented ceiling drift silently: the workflow's own
printed reviewer checklist said "clamped to max_contracts=2" long after the
Phase 3 change quietly raised the real hard cap to 20 (engine/config.py:157-164,
678-694) -- a human could tag a PR "[safety-review]" without the CI ever
confirming what changed, or whether it matched what the tag-adder believed.

This script closes that hole the same way arch_invariant_guard.py closes the
architecture-drift hole: it scans engine/config.py *as text* (no pydantic
import, no engine import, safe to run against an untrusted PR head) and
diffs the live literal values of the documented safety invariants against a
pinned EXPECTED table checked into this file. A silent, undocumented change
to any of these numbers now fails CI outright -- not just "no tag present."
An *intentional* change requires updating EXPECTED here (a real, reviewable
diff line) in the same PR, in addition to the [safety-review] tag.

Not every invariant in the workflow's checklist is a single literal (kill
switch activation paths and stop-loss direction are control-flow, not a
number) -- those remain covered by human review via the tag alone, as
before. This guard covers every invariant that IS a literal value.

Usage (from the engine/ directory, or via `python engine/scripts/...` from
repo root -- CONFIG_PATH is resolved relative to this file either way):
    python -m scripts.check_safety_invariants
    python engine/scripts/check_safety_invariants.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# engine/ -- this file lives at engine/scripts/check_safety_invariants.py
ENGINE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ENGINE_ROOT / "config.py"

# ---------------------------------------------------------------------------
# Pinned expected values. This is the human-reviewed source of truth: bump a
# value here (in the same PR that changes engine/config.py, with a
# [safety-review]-tagged PR body) to intentionally move an invariant.
# Values pulled 2026-07-30 from origin/master (6856c4c) -- confirmed live.
# ---------------------------------------------------------------------------
EXPECTED_FIELD_DEFAULTS: dict[str, float | int] = {
    # -- Position size / capital caps (TradingConfig, engine/config.py) --
    "MAX_POSITION_SIZE_PCT": 0.10,
    "MAX_DAILY_LOSS_PCT": 0.06,
    "MAX_DAILY_LOSS_USD": 100.0,
    "MAX_TRADE_LOSS_USD": 50.0,
    "MAX_DRAWDOWN_PCT": 0.20,
    "MAX_ORDERS_PER_MINUTE": 10,
    "MAX_CORRELATED_EXPOSURE_PCT": 0.50,
    "PRICE_COLLAR_PCT": 0.05,
    "MAX_SINGLE_ORDER_VALUE": 100000.0,
    "MAX_MARGIN_UTILIZATION": 0.40,
    # -- Futures contract caps --
    "MAX_CONTRACTS_PER_INSTRUMENT": 2,  # default; hard cap checked separately below
    "MAX_OVERNIGHT_CONTRACTS": 1,
    "CORRELATED_PAIR_MAX_CONTRACTS": 1,
    # -- Consecutive-loss de-risking ladder --
    "CONSECUTIVE_LOSS_HALF_SIZE": 3,
    "CONSECUTIVE_LOSS_QUARTER_SIZE": 5,
    "CONSECUTIVE_LOSS_HALT": 7,
    "CONSECUTIVE_LOSS_HALT_HOURS": 24,
}

# MAX_CONTRACTS_PER_INSTRUMENT's hard ceiling lives in the
# `_enforce_max_contracts_hard_cap` field_validator, not in the Field()
# default -- a raised env value gets silently clamped to this number rather
# than rejected. This is the exact value that was bumped 2 -> 20 (Phase 3)
# while the CI gate's printed reviewer text kept saying "2".
EXPECTED_MAX_CONTRACTS_HARD_CAP = 20


def _read_config_text() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8")


# Matches `NAME: <type> = Field(<value>, ...)` where <value> is the first
# positional (default) argument, tolerating the value on the same line as
# `Field(` or on its own indented line below it (both styles appear in
# engine/config.py). Deliberately does NOT try to parse Field(default=...)
# keyword style -- config.py uses positional defaults exclusively today; if
# that ever changes this guard should be extended, not silently pass.
_FIELD_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*[^=\n]+=\s*Field\(\s*([^,\n]+),",
    re.MULTILINE,
)


def _parse_literal(raw: str):
    raw = raw.strip()
    try:
        if re.fullmatch(r"-?\d+", raw):
            return int(raw)
        return float(raw)
    except ValueError:
        return None  # not a plain numeric literal (e.g. a dict/env expr) -- skip


def find_field_defaults(text: str) -> dict[str, float | int]:
    found: dict[str, float | int] = {}
    for name, raw_value in _FIELD_RE.findall(text):
        if name not in EXPECTED_FIELD_DEFAULTS:
            continue
        value = _parse_literal(raw_value)
        if value is not None:
            found[name] = value
    return found


_HARD_CAP_RE = re.compile(r"if\s+n\s*>\s*(\d+)\s*:\s*.*?return\s+(\d+)", re.DOTALL)


def find_max_contracts_hard_cap(text: str) -> int | None:
    """Extract the clamp ceiling from `_enforce_max_contracts_hard_cap`.

    Looks for the `if n > X: ... return X` shape and requires both numbers to
    agree (the threshold check and the clamped return value must match, or
    the validator itself is inconsistent and that's worth failing loudly on
    too).
    """
    match = _HARD_CAP_RE.search(text)
    if not match:
        return None
    threshold, clamped = int(match.group(1)), int(match.group(2))
    if threshold != clamped:
        return None
    return threshold


def scan() -> dict:
    """Return {invariant_name: {"expected": ..., "actual": ...}} for every
    invariant whose live value in engine/config.py disagrees with (or is
    missing from) the pinned EXPECTED table."""
    if not CONFIG_PATH.exists():
        return {"__error__": {"expected": "engine/config.py to exist", "actual": "not found"}}

    text = _read_config_text()
    findings: dict = {}

    actual_defaults = find_field_defaults(text)
    for name, expected in EXPECTED_FIELD_DEFAULTS.items():
        actual = actual_defaults.get(name)
        if actual is None:
            findings[name] = {"expected": expected, "actual": "NOT FOUND (Field default unparseable or field renamed/removed)"}
        elif actual != expected:
            findings[name] = {"expected": expected, "actual": actual}

    actual_hard_cap = find_max_contracts_hard_cap(text)
    if actual_hard_cap is None:
        findings["MAX_CONTRACTS_PER_INSTRUMENT_HARD_CAP"] = {
            "expected": EXPECTED_MAX_CONTRACTS_HARD_CAP,
            "actual": "NOT FOUND (validator shape changed -- update _HARD_CAP_RE or re-verify by hand)",
        }
    elif actual_hard_cap != EXPECTED_MAX_CONTRACTS_HARD_CAP:
        findings["MAX_CONTRACTS_PER_INSTRUMENT_HARD_CAP"] = {
            "expected": EXPECTED_MAX_CONTRACTS_HARD_CAP,
            "actual": actual_hard_cap,
        }

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safety-invariant live-value guard.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    findings = scan()

    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        if not findings:
            print(f"safety-invariant guard: all {len(EXPECTED_FIELD_DEFAULTS) + 1} pinned invariants match engine/config.py.")
        else:
            print("safety-invariant guard: LIVE VALUE MISMATCH(ES) DETECTED")
            print("")
            for name, detail in findings.items():
                print(f"  {name}: expected={detail['expected']!r} actual={detail['actual']!r}")
            print("")
            print(
                "If this change is intentional: update EXPECTED_FIELD_DEFAULTS / "
                "EXPECTED_MAX_CONTRACTS_HARD_CAP in engine/scripts/check_safety_invariants.py "
                "in this same PR (so the diff is reviewable) and add the '[safety-review]' tag "
                "to the PR body. If it's NOT intentional, this is exactly the silent-drift bug "
                "this guard exists to catch -- revert the config change."
            )

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
