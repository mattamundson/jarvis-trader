#!/usr/bin/env python3
"""Compatibility entrypoint for the cron-configured position watchdog.

The default-profile cron job is configured with script="jarvis_position_watchdog.py"
from workdir=engine. The maintained watchdog implementation lives under
engine/scripts/independent_position_watchdog.py. Keep this thin wrapper so the
cron path is stable without editing the authoritative cron store.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


_TARGET = Path(__file__).resolve().parent / "scripts" / "independent_position_watchdog.py"


def main() -> int:
    if not _TARGET.exists():
        print(f"POSITION WATCHDOG ERROR: wrapper target missing: {_TARGET}")
        return 1
    try:
        runpy.run_path(str(_TARGET), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
