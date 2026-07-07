#!/usr/bin/env bash
# install-into-repo.sh — install the Paperclip V5 Claude Code pack into a local repo clone
#
# Usage:
#   ./scripts/install-into-repo.sh /path/to/paperclip-clone
#
# What it does:
#   1. Backs up existing .claude/ and CLAUDE.md to a timestamped folder
#   2. Copies .claude/paperclip/docs/ into the repo (new namespace, no collision)
#   3. Copies .claude/agents/paperclip-*.md (namespaced, won't clobber existing agents)
#   4. Copies .claude/commands/paperclip-*.md (namespaced, won't clobber existing commands)
#   5. Creates CLAUDE.md if missing, or appends a managed import block if it exists
#
# What it does NOT do:
#   - Does NOT touch .claude/skills/ (repo has its own skills there)
#   - Does NOT overwrite non-paperclip agents or commands
#   - Does NOT overwrite existing CLAUDE.md content

set -euo pipefail

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-}"

if [[ -z "$TARGET_DIR" ]]; then
  echo "Usage: $0 /path/to/paperclip-clone"
  exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "ERROR: Target directory does not exist: $TARGET_DIR"
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$TARGET_DIR/.claude-backup-$TIMESTAMP"

echo "=== Paperclip V5 Claude Code Pack Installer ==="
echo "Pack:   $PACK_DIR"
echo "Target: $TARGET_DIR"
echo ""

# Step 1: Backup
echo "--- Step 1: Backing up existing .claude/ and CLAUDE.md ---"
mkdir -p "$BACKUP_DIR"

if [[ -d "$TARGET_DIR/.claude" ]]; then
  cp -r "$TARGET_DIR/.claude" "$BACKUP_DIR/.claude"
  echo "  Backed up .claude/ → $BACKUP_DIR/.claude"
fi

if [[ -f "$TARGET_DIR/CLAUDE.md" ]]; then
  cp "$TARGET_DIR/CLAUDE.md" "$BACKUP_DIR/CLAUDE.md"
  echo "  Backed up CLAUDE.md → $BACKUP_DIR/CLAUDE.md"
fi

# Step 2: Copy .claude/paperclip/docs/ (new namespace, safe)
echo ""
echo "--- Step 2: Copying .claude/paperclip/docs/ ---"
mkdir -p "$TARGET_DIR/.claude/paperclip/docs"
cp -r "$PACK_DIR/.claude/paperclip/docs/." "$TARGET_DIR/.claude/paperclip/docs/"
echo "  Copied .claude/paperclip/docs/ ($(ls "$PACK_DIR/.claude/paperclip/docs/" | wc -l | tr -d ' ') files)"

# Step 3: Copy agents (namespaced paperclip-*.md only)
echo ""
echo "--- Step 3: Copying .claude/agents/paperclip-*.md ---"
mkdir -p "$TARGET_DIR/.claude/agents"
for f in "$PACK_DIR/.claude/agents"/paperclip-*.md; do
  [[ -f "$f" ]] || continue
  name="$(basename "$f")"
  cp "$f" "$TARGET_DIR/.claude/agents/$name"
  echo "  Copied: .claude/agents/$name"
done

# Step 4: Copy commands (namespaced paperclip-*.md only)
echo ""
echo "--- Step 4: Copying .claude/commands/paperclip-*.md ---"
mkdir -p "$TARGET_DIR/.claude/commands"
for f in "$PACK_DIR/.claude/commands"/paperclip-*.md; do
  [[ -f "$f" ]] || continue
  name="$(basename "$f")"
  cp "$f" "$TARGET_DIR/.claude/commands/$name"
  echo "  Copied: .claude/commands/$name"
done

# Step 5: CLAUDE.md — create or merge
echo ""
echo "--- Step 5: CLAUDE.md ---"
IMPORT_BLOCK='<!-- paperclip-pack-v5 -->
@.claude/paperclip/docs/root-memory.md
<!-- /paperclip-pack-v5 -->'

if [[ ! -f "$TARGET_DIR/CLAUDE.md" ]]; then
  echo "  No CLAUDE.md found — copying from pack"
  cp "$PACK_DIR/CLAUDE.md" "$TARGET_DIR/CLAUDE.md"
else
  # Check if already installed
  if grep -q "paperclip-pack-v5" "$TARGET_DIR/CLAUDE.md" 2>/dev/null; then
    echo "  CLAUDE.md already has paperclip-pack-v5 block — skipping merge"
  else
    echo "  Appending import block to existing CLAUDE.md"
    echo "" >> "$TARGET_DIR/CLAUDE.md"
    echo "$IMPORT_BLOCK" >> "$TARGET_DIR/CLAUDE.md"
    echo "  Done — appended import block"
  fi
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "Backup location: $BACKUP_DIR"
echo ""
echo "Verify with:"
echo "  ls $TARGET_DIR/.claude/paperclip/docs/"
echo "  ls $TARGET_DIR/.claude/agents/ | grep paperclip"
echo "  ls $TARGET_DIR/.claude/commands/ | grep paperclip"
echo "  grep -r 'skills/' $TARGET_DIR/.claude/paperclip/ # should be empty"
echo ""
echo "To use in Claude Code:"
echo "  cd $TARGET_DIR"
echo "  claude"
echo "  /paperclip-orient"
