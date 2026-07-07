#!/usr/bin/env bash
#
# delete_merged_branches.sh — delete remote branches that are DEFINITIVELY merged.
#
# "Definitively merged" = the branch tip is an ancestor of origin/master, i.e. its
# every commit is already in master's history. Deleting it loses nothing — the exact
# commits remain reachable from master, so it's fully recoverable.
#
# This is the safe subset of the open-sessions cleanup (docs/audit/open-sessions-*.md).
# It does NOT touch zero-delta-via-squash branches or anything with unique content —
# those need the review harness (scripts/audit/gather_branch_evidence.sh) first.
#
# DRY-RUN by default. Run from the repo root, on a machine with push rights:
#   bash scripts/audit/delete_merged_branches.sh            # list only
#   bash scripts/audit/delete_merged_branches.sh --execute  # actually delete
#
set -uo pipefail

MASTER="origin/master"
EXECUTE=0
[ "${1:-}" = "--execute" ] && EXECUTE=1

if [ ! -d .git ]; then
  echo "ERROR: run from the repo root." >&2
  exit 1
fi

echo "Fetching + pruning..."
git fetch origin --prune >/dev/null 2>&1 || echo "warn: fetch failed; using local refs" >&2

MERGED=()
while IFS= read -r b; do
  [ -z "$b" ] && continue
  if git merge-base --is-ancestor "origin/$b" "$MASTER" 2>/dev/null; then
    MERGED+=("$b")
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin \
           | grep -v '/HEAD$' | grep -v '^origin/master$' | sed 's#origin/##')

n=${#MERGED[@]}
if [ "$n" -eq 0 ]; then
  echo "No fully-merged remote branches to delete."
  exit 0
fi

echo
echo "$n remote branch(es) are fully merged (tip is an ancestor of master) — safe to delete:"
for b in "${MERGED[@]}"; do
  printf "  %-52s %s\n" "$b" "$(git rev-parse --short "origin/$b" 2>/dev/null)"
done

if [ "$EXECUTE" -eq 1 ]; then
  echo
  echo "Deleting $n branch(es)..."
  git push origin --delete "${MERGED[@]}"
  echo "Done. (Recover any of the above with: git push origin <sha>:refs/heads/<name>)"
else
  echo
  echo "DRY-RUN — nothing deleted. Re-run with --execute to delete."
  echo "Every branch above is already in master's history, so this is safe and reversible."
fi
