#!/usr/bin/env python3
"""Minimal test runner (no pytest required)."""
from __future__ import annotations
import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    failed = passed = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            print("LOAD FAIL", path.name)
            traceback.print_exc()
            failed += 1
            continue
        for name in sorted(dir(mod)):
            if name.startswith("test_") and callable(getattr(mod, name)):
                try:
                    getattr(mod, name)()
                    print("PASS", path.name, name)
                    passed += 1
                except Exception:
                    print("FAIL", path.name, name)
                    traceback.print_exc()
                    failed += 1
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
