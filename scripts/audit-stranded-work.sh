#!/usr/bin/env bash
# audit-stranded-work.sh
#
# Surface "committed but never pushed" work and other stranded git state so it
# does not rot silently on a developer machine. Read-only apart from an optional
# remote refresh (git fetch). Run this where the work actually lives -- a fresh
# CI/cloud clone shows nothing because it only has what is already on origin.
#
# Usage:
#   scripts/audit-stranded-work.sh             # fetch, then audit
#   scripts/audit-stranded-work.sh --no-fetch  # audit without touching the network

set -euo pipefail

DO_FETCH=1
[ "${1:-}" = "--no-fetch" ] && DO_FETCH=0

cd "$(git rev-parse --show-toplevel)"

if [ "$DO_FETCH" -eq 1 ]; then
  echo "Fetching remotes (use --no-fetch to skip)..."
  git fetch --all --quiet || echo "  WARNING: fetch failed; ahead/behind counts may be stale"
  echo ""
fi

ahead_total=0
noupstream_total=0

echo "=== Local branches ahead of / behind their upstream ==="
while IFS= read -r branch; do
  upstream=$(git rev-parse --abbrev-ref "$branch@{upstream}" 2>/dev/null || true)
  [ -z "$upstream" ] && continue
  # rev-list --left-right --count <upstream>...<branch> prints: "<behind>\t<ahead>"
  read -r behind ahead < <(git rev-list --left-right --count "$upstream...$branch")
  if [ "$ahead" -gt 0 ] || [ "$behind" -gt 0 ]; then
    flag=""
    if [ "$ahead" -gt 0 ]; then
      flag="  <-- UNPUSHED: $ahead commit(s) not on $upstream"
      ahead_total=$((ahead_total + 1))
    fi
    printf "  %-45s ahead %s / behind %s%s\n" "$branch" "$ahead" "$behind" "$flag"
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)
[ "$ahead_total" -eq 0 ] && echo "  (none ahead -- nothing committed-but-unpushed)"
echo ""

echo "=== Local branches with NO upstream (never pushed anywhere) ==="
while IFS= read -r branch; do
  if ! git rev-parse --abbrev-ref "$branch@{upstream}" >/dev/null 2>&1; then
    # commits on this branch that exist on no remote -- the truly stranded ones
    n=$(git rev-list --count "$branch" --not --remotes)
    echo "  $branch  ($n commit(s) on no remote)"
    noupstream_total=$((noupstream_total + 1))
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)
[ "$noupstream_total" -eq 0 ] && echo "  (none)"
echo ""

echo "=== Worktrees (the staged-not-pushed worktree pattern) ==="
git worktree list
echo ""

echo "=== Stashes (parked uncommitted work) ==="
if git stash list | grep -q .; then git stash list; else echo "  (none)"; fi
echo ""

echo "=== Working-tree changes (current worktree only) ==="
mod=$(git status --porcelain | grep -vc '^??' || true)
unt=$(git status --porcelain | grep -c '^??' || true)
echo "  tracked modified/staged: $mod"
echo "  untracked:               $unt  (jarvis-trader carries many legit untracked files; review, do not blanket-add)"
echo ""

echo "=== Summary ==="
echo "  branches with unpushed commits: $ahead_total"
echo "  branches never pushed:          $noupstream_total"
if [ "$ahead_total" -gt 0 ] || [ "$noupstream_total" -gt 0 ]; then
  echo "  ACTION: review and push the flagged branches (git push -u origin <branch>) before the work is lost."
  exit 1
fi
echo "  Clean: no committed-but-unpushed work."
