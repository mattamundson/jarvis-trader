#!/usr/bin/env bash
# ============================================================================
# Event:      UserPromptSubmit
# Purpose:    Inject a one-line engine health + timestamp banner into context.
#             Keeps Matt aware of whether the jarvis-engine is responsive
#             without requiring a manual /health check each turn.
# Pattern:    ravila4__claude-adhd-skills (UserPromptSubmit time/alert hook)
# Cost:       ~150ms on localhost. No LLM calls, no external network.
# Disable:    Remove from settings.local.json hooks.UserPromptSubmit[], or
#             `chmod -x` this file. Hook always exits 0 — prompt still flows.
# ============================================================================
set -u

NOW="$(date '+%Y-%m-%d %H:%M %Z')"

# Hit /health with a 1s hard timeout. Engine is at localhost:8010.
HEALTH="$(curl -sS --max-time 1 http://localhost:8010/health 2>/dev/null || echo '')"

if [[ -z "$HEALTH" ]]; then
  STATUS="DOWN (port 8010 unreachable — run .\\restart_engine.ps1)"
elif echo "$HEALTH" | grep -q '"status":"ok"'; then
  STATUS="UP"
elif echo "$HEALTH" | grep -q '"status":"degraded"'; then
  STATUS="DEGRADED"
else
  STATUS="UNKNOWN (/health returned unexpected payload)"
fi

# UserPromptSubmit hooks: stdout is appended to the user's prompt as context.
# Keep it short — this fires on EVERY prompt.
echo "[jarvis] ${NOW} | engine:${STATUS}"
exit 0
