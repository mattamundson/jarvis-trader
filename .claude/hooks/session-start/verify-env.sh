#!/usr/bin/env bash
# ============================================================================
# Event:      SessionStart (matcher: startup|resume)
# Purpose:    Verify engine/.env has required keys and warn if LIVE_TRADING_ENABLED=true
# Pattern:    ravila4__claude-adhd-skills (UserPromptSubmit env-awareness pattern,
#             adapted to SessionStart + env-file validation)
# Disable:    Remove the "verify-env.sh" entry from .claude/settings.local.json
#             under hooks.SessionStart[].hooks, OR `chmod -x` this file.
# Exit:       Always 0 (never blocks the session). Warnings go to stderr.
# ============================================================================
set -u

ENV_FILE="${CLAUDE_PROJECT_DIR:-$(pwd)}/engine/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[verify-env] WARN: engine/.env not found at $ENV_FILE" >&2
  exit 0
fi

# Required keys for the engine to boot cleanly
REQUIRED=(API_KEY ANTHROPIC_API_KEY POLYGON_API_KEY)
MISSING=()
for key in "${REQUIRED[@]}"; do
  if ! grep -qE "^${key}=.+" "$ENV_FILE" 2>/dev/null; then
    MISSING+=("$key")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "[verify-env] WARN: engine/.env missing or empty keys: ${MISSING[*]}" >&2
fi

# Loud warning if live trading was left on
if grep -qE "^LIVE_TRADING_ENABLED=true" "$ENV_FILE" 2>/dev/null; then
  echo "" >&2
  echo "========================================================" >&2
  echo "[verify-env] !!! LIVE_TRADING_ENABLED=true !!!" >&2
  echo "[verify-env] You are NOT on paper. IB port should be 4002," >&2
  echo "[verify-env] live port 4001 is PERMANENTLY BLOCKED." >&2
  echo "[verify-env] Set LIVE_TRADING_ENABLED=false in engine/.env" >&2
  echo "[verify-env] unless this is intentional." >&2
  echo "========================================================" >&2
  echo "" >&2
fi

exit 0
