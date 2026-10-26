#!/usr/bin/env python3
"""Validate all 10 strategy registry entries against schema.json."""
import json
import os
import sys
from pathlib import Path

repo = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader")
schema_path = repo / "docs/research/strategy-registry/schema.json"
entries_dir = repo / "docs/research/strategy-registry/entries"

schema = json.loads(schema_path.read_text())
errors = []
checked = 0

for entry_path in sorted(entries_dir.glob("*.json")):
    checked += 1
    try:
        entry = json.loads(entry_path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"PARSE FAIL  {entry_path.name}: {e}")
        continue

    required = schema.get("required", [])
    missing = [f for f in required if f not in entry]
    if missing:
        errors.append(f"MISSING    {entry_path.name}: {', '.join(missing)}")
        continue

    sv = entry.get("schema_version")
    if sv != "1.0":
        errors.append(f"VERSION    {entry_path.name}: schema_version={sv!r} (expected '1.0')")

    sid = entry.get("strategy_id", "")
    import re
    if not re.match(r"^[a-z0-9]+(_[a-z0-9]+)+$", sid):
        errors.append(f"ID_PATTERN {entry_path.name}: strategy_id={sid!r} does not match ^[a-z0-9]+(_[a-z0-9]+)+$")

    source = entry.get("source", {})
    stype = source.get("type")
    allowed = {"x-bookmark-scan", "imported-repo", "internal-idea", "llm-generated", "adapted", "human"}
    if stype not in allowed:
        errors.append(f"SRC_TYPE   {entry_path.name}: source.type={stype!r} not in {allowed}")

    asset = entry.get("asset_class")
    allowed_asset = {"equity-index", "future", "option", "forex", "crypto", "prediction-market"}
    if asset not in allowed_asset:
        errors.append(f"ASSET      {entry_path.name}: asset_class={asset!r} not in {allowed_asset}")

    symbols = entry.get("symbols")
    if not isinstance(symbols, list) or len(symbols) < 1:
        errors.append(f"SYMBOLS    {entry_path.name}: symbols must be non-empty array")

    status = "OK  "
    print(f"{status}  {entry_path.name}  sid={sid}  promotion={entry.get('promotion_state')}  verdict={entry['gate_verdict']['verdict']}  source={stype}  asset={asset}  symbols={symbols}")

if errors:
    print("\n=== ERRORS ===")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print(f"\nAll {checked} entries validated OK against schema.json")
    sys.exit(0)
