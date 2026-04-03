#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /absolute/or/relative/path/to/paperclip-clone [--dry-run]" >&2
  exit 1
fi

TARGET="$1"
DRY_RUN="${2:-}"
PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$(cd "$TARGET" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$TARGET/.paperclip-claude-backup-$STAMP"

run() {
  if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "[dry-run] $*"
  else
    eval "$*"
  fi
}

if [[ ! -d "$TARGET" ]]; then
  echo "Target does not exist: $TARGET" >&2
  exit 1
fi

mkdir_cmd="mkdir -p '$BACKUP_DIR'"
run "$mkdir_cmd"

if [[ -e "$TARGET/CLAUDE.md" ]]; then
  run "cp '$TARGET/CLAUDE.md' '$BACKUP_DIR/CLAUDE.md'"
fi
if [[ -d "$TARGET/.claude" ]]; then
  run "cp -R '$TARGET/.claude' '$BACKUP_DIR/.claude'"
fi

run "mkdir -p '$TARGET/.claude'"
run "cp -R '$PACK_DIR/.claude/.' '$TARGET/.claude/'"

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  python3 "$PACK_DIR/scripts/merge-claude-md.py" "$TARGET/CLAUDE.md" "$PACK_DIR/CLAUDE.md" --dry-run
else
  python3 "$PACK_DIR/scripts/merge-claude-md.py" "$TARGET/CLAUDE.md" "$PACK_DIR/CLAUDE.md"
fi

echo "Installed Paperclip Claude Code pack into: $TARGET"
echo "Backup location: $BACKUP_DIR"
echo "Next steps:"
echo "  1. cd '$TARGET'"
echo "  2. open Claude Code in the repo"
echo "  3. run /memory to confirm CLAUDE.md is loaded"
echo "  4. run /help to confirm project commands are visible"
echo "  5. run /agents to confirm project subagents are visible"
