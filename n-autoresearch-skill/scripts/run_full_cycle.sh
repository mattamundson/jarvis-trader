#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

exec python "$SCRIPT_DIR/run_full_cycle.py" --repo-dir "$REPO_DIR" "$@"
