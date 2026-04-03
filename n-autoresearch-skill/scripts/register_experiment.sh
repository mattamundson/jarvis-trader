#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "usage: $0 <tag> <category> <description> <hypothesis> <diff_summary> [parent_id]"
  exit 1
fi

TAG="$1"
CATEGORY="$2"
DESCRIPTION="$3"
HYPOTHESIS="$4"
DIFF_SUMMARY="$5"
PARENT_ID="${6:-null}"
COMMIT="$(git rev-parse --short HEAD)"

if [[ "$PARENT_ID" == "null" ]]; then
  PARENT_FIELD='null'
else
  PARENT_FIELD="\"$PARENT_ID\""
fi

curl -sS -X POST http://localhost:3111/api/experiment/register \
  -H 'Content-Type: application/json' \
  -d "{
    \"tag\": \"$TAG\",
    \"hypothesis\": \"$HYPOTHESIS\",
    \"description\": \"$DESCRIPTION\",
    \"category\": \"$CATEGORY\",
    \"commit_sha\": \"$COMMIT\",
    \"diff_summary\": \"$DIFF_SUMMARY\",
    \"parent_id\": $PARENT_FIELD
  }"
