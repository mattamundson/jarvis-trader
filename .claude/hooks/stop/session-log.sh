#!/usr/bin/env bash
# ============================================================================
# Event:      Stop
# Purpose:    Append a one-line session-close stub to docs/session-logs/
#             so milestone handoffs have a starting point. Matt still runs
#             a proper YAML handoff at real milestones — this is just the
#             breadcrumb so blank stubs never happen (see MEMORY.md note on
#             Obsidian Stop hook that "only prints reminders, never populates").
# Pattern:    affaan-m__everything-claude-code (Stop-phase session summaries)
#             thedotmack__claude-mem (Stop lifecycle hook)
# Cost:       ~10ms. Pure bash, no network, no LLM.
# Disable:    Remove from settings.local.json hooks.Stop[], or `chmod -x`.
# ============================================================================
set -u

PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG_DIR="$PROJECT/docs/session-logs"
mkdir -p "$LOG_DIR" 2>/dev/null || exit 0

DATE="$(date '+%Y-%m-%d')"
STAMP="$(date '+%H:%M:%S %Z')"
LOG_FILE="$LOG_DIR/stop-stubs-${DATE}.md"

# Create header if file is new
if [[ ! -f "$LOG_FILE" ]]; then
  {
    echo "# Stop-hook stubs — ${DATE}"
    echo ""
    echo "> Auto-generated breadcrumbs. One line per Stop event."
    echo "> For real handoffs use docs/session-logs/HANDOFF_TEMPLATE.md."
    echo ""
  } >"$LOG_FILE"
fi

# Append line. We don't have session context here (Stop payload is minimal),
# so keep it factual: timestamp + cwd + git HEAD short SHA.
GIT_SHA="$(git -C "$PROJECT" rev-parse --short HEAD 2>/dev/null || echo 'no-git')"
GIT_DIRTY=""
if ! git -C "$PROJECT" diff --quiet 2>/dev/null; then
  GIT_DIRTY=" (dirty)"
fi

echo "- ${STAMP} | HEAD=${GIT_SHA}${GIT_DIRTY}" >>"$LOG_FILE"

exit 0
