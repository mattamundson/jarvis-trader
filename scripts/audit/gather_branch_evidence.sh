#!/usr/bin/env bash
#
# gather_branch_evidence.sh — forensic evidence gatherer for the open-branch review.
#
# Follow-up to docs/audit/open-sessions-2026-06-29.md. That audit bucketed ~200
# branches; this script produces the EVIDENCE needed to review each one BEFORE any
# deletion, and packages it into batches you can hand to separate Claude Code
# review sessions (see docs/audit/BRANCH_REVIEW_PLAYBOOK.md).
#
# IT DELETES NOTHING. It only reads git and writes markdown under
# docs/audit/branch-review/ (gitignored — these are working artifacts).
#
# Why "zero content delta" is NOT enough to delete: an empty three-dot diff can mean
# "fully merged → safe" OR "the work was squash-merged" OR "the work was reverted out
# of master and may be worth RECOVERING". This script captures the facts that tell
# those apart (is the tip an ancestor of master? what are the unique commits? was
# anything reverted?) so a reviewer can decide with evidence, not a heuristic.
#
# Usage (from repo root):
#   bash scripts/audit/gather_branch_evidence.sh
#   bash scripts/audit/gather_branch_evidence.sh --no-fetch     # skip the network fetch
#
set -uo pipefail

MASTER="origin/master"
OUT="docs/audit/branch-review"
EVID="$OUT/evidence"
BATCHDIR="$OUT/batches"
VERDICTS="$OUT/verdicts"
ZERO_BATCH=20   # zero-delta branches per review session (quick)
GIANT_BATCH=5   # giant branches per review session (deep)
MID_BATCH=10    # mid-size branches per review session

if [ ! -d .git ]; then
  echo "ERROR: run from the repo root (no .git here)." >&2
  exit 1
fi

mkdir -p "$EVID" "$BATCHDIR" "$VERDICTS"
MANIFEST="$OUT/_manifest.psv"   # class|branch|files|ins|uniq|merged
: > "$MANIFEST"

if [ "${1:-}" != "--no-fetch" ]; then
  echo "Fetching all remote branches (prune)..."
  git fetch origin '+refs/heads/*:refs/remotes/origin/*' --prune >/dev/null 2>&1 || \
    echo "warn: fetch failed; proceeding with local refs" >&2
fi

# Count of commits in master..ref reachable from a 'Revert' — a heuristic that the
# branch's work may have been undone in master and is therefore a RECOVER candidate.
_reverted_hint() {
  git log --format='%s' "$MASTER..$1" 2>/dev/null | grep -ciE '^revert' || true
}

echo "Scanning branches..."
N=0
while IFS= read -r ref; do
  br="${ref#origin/}"
  safe="$(printf '%s' "$br" | tr '/' '__')"

  shortstat="$(git diff --shortstat "$MASTER...$ref" 2>/dev/null)"
  files="$(printf '%s' "$shortstat" | grep -oE '[0-9]+ file' | grep -oE '[0-9]+' || true)"; files="${files:-0}"
  ins="$(printf '%s' "$shortstat" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || true)"; ins="${ins:-0}"
  uniq_n="$(git rev-list --count "$MASTER..$ref" 2>/dev/null || echo 0)"
  mb="$(git merge-base "$MASTER" "$ref" 2>/dev/null || echo '')"

  if git merge-base --is-ancestor "$ref" "$MASTER" 2>/dev/null; then
    merged="YES"   # tip is literally in master history => fully merged
  else
    merged="no"
  fi

  if [ "$files" -eq 0 ]; then cls="ZERO_DELTA"
  elif [ "$files" -gt 30 ]; then cls="GIANT"
  else cls="MID"; fi

  reverts="$(_reverted_hint "$ref")"

  {
    echo "### \`$br\`"
    echo
    echo "| field | value |"
    echo "|---|---|"
    echo "| classification | **$cls** |"
    echo "| tip is ancestor of master (fully merged) | **$merged** |"
    echo "| true delta vs master (three-dot) | ${files} files / +${ins} lines |"
    echo "| unique commits (master..branch) | ${uniq_n} |"
    echo "| 'Revert' commits among unique | ${reverts} |"
    echo "| last commit | $(git log -1 --format='%cs · %an · %s' "$ref" 2>/dev/null) |"
    echo "| merge-base | ${mb:0:9} ($(git log -1 --format='%cs %s' "$mb" 2>/dev/null)) |"
    echo
    echo "<details><summary>Unique commit subjects (master..branch, capped 60)</summary>"
    echo
    echo '```'
    git log --format='%h %cs %s' "$MASTER..$ref" 2>/dev/null | head -60
    echo '```'
    echo "</details>"
    echo
    echo "<details><summary>Files changed vs merge-base (name-status, capped 100)</summary>"
    echo
    echo '```'
    git diff --name-status "$MASTER...$ref" 2>/dev/null | head -100
    echo '```'
    echo "</details>"
    echo
  } > "$EVID/$safe.md"

  printf '%s|%s|%s|%s|%s|%s\n' "$cls" "$br" "$files" "$ins" "$uniq_n" "$merged" >> "$MANIFEST"
  N=$((N + 1))
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin \
           | grep -v '/HEAD$' | grep -v '^origin/master$')

echo "Gathered evidence for $N branches."

# ── batch builder: group one class into self-contained review files ───────────────
_emit_batches() {
  local class="$1" size="$2" prefix="$3"
  local list n i=0 b=0 file
  list="$(awk -F'|' -v c="$class" '$1==c{print $2}' "$MANIFEST" | sort)"
  [ -z "$list" ] && return 0
  n="$(printf '%s\n' "$list" | grep -c . )"
  while IFS= read -r br; do
    if [ $((i % size)) -eq 0 ]; then
      b=$((b + 1))
      file="$(printf '%s/%s-%02d.md' "$BATCHDIR" "$prefix" "$b")"
      {
        echo "# Review batch ${prefix}-$(printf '%02d' "$b") ($class)"
        echo
        echo "> Review EACH branch below per \`docs/audit/BRANCH_REVIEW_PLAYBOOK.md\`."
        echo "> Emit a verdict line per branch into \`$VERDICTS/${prefix}-$(printf '%02d' "$b").md\`."
        echo "> Verdicts: SAFE-DELETE · RECOVER · KEEP-OPEN · ESCALATE — each with a one-line justification."
        echo
      } > "$file"
    fi
    safe="$(printf '%s' "$br" | tr '/' '__')"
    cat "$EVID/$safe.md" >> "$file"
    i=$((i + 1))
  done < <(printf '%s\n' "$list")
  echo "  $class: $n branches -> $b batch file(s) of up to $size"
}

echo "Building batches..."
_emit_batches ZERO_DELTA "$ZERO_BATCH" "zero"
_emit_batches MID        "$MID_BATCH"  "mid"
_emit_batches GIANT      "$GIANT_BATCH" "giant"

# ── RUN.md: the operator index with paste-ready session prompts ───────────────────
RUN="$OUT/RUN.md"
{
  echo "# Branch review — run book ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  echo
  echo "Generated by \`scripts/audit/gather_branch_evidence.sh\`. Nothing has been deleted."
  echo
  echo "## Totals"
  echo
  echo "| class | branches |"
  echo "|---|---|"
  for c in ZERO_DELTA MID GIANT; do
    echo "| $c | $(awk -F'|' -v c="$c" '$1==c' "$MANIFEST" | grep -c . ) |"
  done
  echo
  echo "## How to review (one batch = one fresh Claude Code session)"
  echo
  echo "For each batch file in \`$BATCHDIR/\`, open a NEW session and paste:"
  echo
  echo '```'
  echo "Review every branch in @$BATCHDIR/<batch-file> following the rubric in"
  echo "@docs/audit/BRANCH_REVIEW_PLAYBOOK.md. For each branch emit one verdict line"
  echo "(SAFE-DELETE | RECOVER | KEEP-OPEN | ESCALATE) with a one-sentence justification,"
  echo "and write them to docs/audit/branch-review/verdicts/<same-batch-name>. Do NOT"
  echo "delete any branch or open any PR — produce verdicts only."
  echo '```'
  echo
  echo "## Batches"
  echo
  for f in "$BATCHDIR"/*.md; do
    [ -e "$f" ] || continue
    echo "- \`$f\` — $(grep -c '^### ' "$f") branches"
  done
  echo
  echo "## After verdicts are in"
  echo
  echo "- SAFE-DELETE: \`git push origin --delete <branch>\` (batchable once a human signs off)."
  echo "- RECOVER: cherry-pick / re-implement the unique content into a fresh <30-file PR off master, THEN delete."
  echo "- KEEP-OPEN: leave; ensure it has an open PR on the in-flight list."
  echo "- ESCALATE: bring to the user — touches safety files, looks reverted, or value unclear."
} > "$RUN"

echo
echo "DONE. Start here: $RUN"
echo "Evidence:  $EVID/   Batches: $BATCHDIR/   Verdicts go to: $VERDICTS/"
