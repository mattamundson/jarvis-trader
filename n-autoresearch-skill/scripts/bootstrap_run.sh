#!/usr/bin/env bash
set -euo pipefail

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "usage: $0 <tag>"
  exit 1
fi

curl -sS -X POST http://localhost:3111/api/experiment/setup \
  -H 'Content-Type: application/json' \
  -d "{\"tag\":\"$TAG\"}"

git checkout -b "autoresearch/$TAG"

echo "Created branch autoresearch/$TAG"
echo "Next: run a baseline experiment unchanged before editing train.py"
