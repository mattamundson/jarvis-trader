#!/usr/bin/env bash
set -euo pipefail

BASE_REF="${1:-HEAD~1}"
TARGET_REF="${2:-HEAD}"

echo "Reviewing ${BASE_REF}..${TARGET_REF}"

echo
printf '%s
' '[1/4] changed files'
git diff --name-only "$BASE_REF" "$TARGET_REF"

CHANGED_COUNT="$(git diff --name-only "$BASE_REF" "$TARGET_REF" | wc -l | tr -d ' ')"
TRAIN_ONLY="$(git diff --name-only "$BASE_REF" "$TARGET_REF")"

echo
printf '%s
' '[2/4] scope guard'
if [[ "$CHANGED_COUNT" == "1" && "$TRAIN_ONLY" == "train.py" ]]; then
  echo "PASS: only train.py changed"
else
  echo "WARN: latest experiment touched files beyond train.py"
fi

echo
printf '%s
' '[3/4] diff stat'
git diff --stat "$BASE_REF" "$TARGET_REF"

echo
printf '%s
' '[4/4] train.py diff preview'
git diff "$BASE_REF" "$TARGET_REF" -- train.py | sed -n '1,220p'
