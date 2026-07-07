#!/usr/bin/env python3
"""
merge-claude-md.py — safely append the Paperclip V5 import block to an existing CLAUDE.md

Usage:
    python scripts/merge-claude-md.py /path/to/repo/CLAUDE.md

Appends:
    @.claude/paperclip/docs/root-memory.md

Idempotent — checks for the marker before appending.
"""

import sys
import os
from pathlib import Path

MARKER = "paperclip-pack-v5"
IMPORT_BLOCK = """
<!-- paperclip-pack-v5 -->
@.claude/paperclip/docs/root-memory.md
<!-- /paperclip-pack-v5 -->
"""

def main():
    if len(sys.argv) < 2:
        print("Usage: python merge-claude-md.py /path/to/CLAUDE.md")
        sys.exit(1)

    target = Path(sys.argv[1])

    if not target.exists():
        print(f"Creating new CLAUDE.md at: {target}")
        target.write_text(IMPORT_BLOCK.strip() + "\n")
        print("Done.")
        return

    content = target.read_text(encoding="utf-8")

    if MARKER in content:
        print(f"Marker '{MARKER}' already found in {target} — skipping.")
        return

    # Backup
    backup = target.with_suffix(f".pre-v5.md")
    backup.write_text(content, encoding="utf-8")
    print(f"Backed up to: {backup}")

    # Append
    updated = content.rstrip() + "\n" + IMPORT_BLOCK
    target.write_text(updated, encoding="utf-8")
    print(f"Appended import block to: {target}")
    print("Done.")

if __name__ == "__main__":
    main()
