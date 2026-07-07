#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

MANAGED_BEGIN = "<!-- BEGIN paperclip-claude-pack -->"
MANAGED_END = "<!-- END paperclip-claude-pack -->"
IMPORT_LINE = "@.claude/paperclip/imports/root-memory.md"


def build_block() -> str:
    return f"{MANAGED_BEGIN}\n{IMPORT_LINE}\n{MANAGED_END}\n"


def merge(target: Path, incoming: Path, dry_run: bool = False) -> str:
    if not target.exists():
        if dry_run:
            return f"[dry-run] Would create {target} from {incoming}."
        target.write_text(incoming.read_text())
        return f"Created {target}."

    text = target.read_text()
    if IMPORT_LINE in text or MANAGED_BEGIN in text:
        return f"No change needed: {target} already references the Paperclip pack."

    new_text = text.rstrip() + "\n\n" + build_block()
    if dry_run:
        return f"[dry-run] Would append managed import block to {target}."
    target.write_text(new_text)
    return f"Updated {target} with a managed import block."


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Merge the Paperclip Claude pack into an existing CLAUDE.md safely.'
    )
    parser.add_argument('target_claude_md', type=Path)
    parser.add_argument('incoming_claude_md', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(merge(args.target_claude_md, args.incoming_claude_md, dry_run=args.dry_run))
