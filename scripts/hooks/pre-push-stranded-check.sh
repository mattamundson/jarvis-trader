#!/usr/bin/env bash
# pre-push-stranded-check.sh
#
# Non-blocking pre-push reminder. Warns when OTHER local branches carry
# committed-but-unpushed work, so it does not rot silently. NEVER blocks the
# push -- it always exits 0. Wraps scripts/audit-stranded-work.sh.
#
# Enable (opt-in, one of):
#   ln -sf ../../scripts/hooks/pre-push-stranded-check.sh .git/hooks/pre-push
#   # or, if you manage hooks centrally:
#   git config core.hooksPath scripts/hooks   # then name this file 'pre-push'
#
# Git passes the remote name/URL as args and the refs being pushed on stdin;
# this wrapper ignores both and only reports cross-branch stranded state.

repo="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
audit="$repo/scripts/audit-stranded-work.sh"
[ -x "$audit" ] || exit 0

# --no-fetch keeps the hook fast and offline-safe; audit exits non-zero when it
# finds stranded work, which is fine here -- we never propagate that as a block.
out="$("$audit" --no-fetch 2>/dev/null || true)"

if printf '%s\n' "$out" | grep -q 'UNPUSHED'; then
  echo "[pre-push] heads up -- committed-but-unpushed work on other local branches:"
  printf '%s\n' "$out" | grep 'UNPUSHED'
  echo "[pre-push] non-blocking. Full picture: scripts/audit-stranded-work.sh"
fi

exit 0
