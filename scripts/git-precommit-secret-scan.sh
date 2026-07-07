#!/usr/bin/env bash
# git-precommit-secret-scan.sh -- pre-commit hook to block secret-bearing commits
#
# Defense-in-depth beyond Claude Code: catches plaintext secrets that any
# tool (terminal git, IDE, automation) would commit. Same pattern set as
# ~/.claude/hooks/credential-guard.sh + scan-credentials.ps1.
#
# Install per-repo:
#   ln -sf ~/scripts/git-precommit-secret-scan.sh .git/hooks/pre-commit
#
# Install globally (every repo):
#   git config --global core.hooksPath ~/scripts/git-hooks/
#   mkdir -p ~/scripts/git-hooks
#   ln -sf ~/scripts/git-precommit-secret-scan.sh ~/scripts/git-hooks/pre-commit
# (NOTE: globally-installed git hooks override existing per-repo hooks. Verify
# none of your active repos depend on per-repo hooks BEFORE doing this.)
#
# Bypass for one-time legitimate need:
#   git commit --no-verify -m "..."
# (Don't make this a habit -- the hook exists because the patterns it catches
# are real production credentials.)

set -u

# Patterns. Keep in sync with ~/.claude/rules/secret-hygiene.md.
SECRET_PATTERNS='sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-|admin-)?[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16}|AIzaSy[A-Za-z0-9_-]{30,}|(ghp|github_pat)_[A-Za-z0-9_]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|rnd_[A-Za-z0-9]{20,}|-----BEGIN ((RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----'

# Forbidden filenames -- block if anyone tries to commit a literal cred file.
FORBIDDEN_FILES='(^|/)(jarvis\.env|\.env\.production|\.env\.prod|\.secrets/keys\.env|\.aider/oauth-keys\.env)$'

# Get list of staged files (added or modified).
files="$(git diff --cached --name-only --diff-filter=AM 2>/dev/null)"
if [ -z "$files" ]; then exit 0; fi

violations=""

# Check 1: forbidden filenames being committed.
while IFS= read -r f; do
  if [ -z "$f" ]; then continue; fi
  if printf '%s' "$f" | grep -qE "$FORBIDDEN_FILES"; then
    violations="${violations}  FORBIDDEN-FILE: $f${NL}"
    NL=$'\n'
  fi
done <<< "$files"

# Check 2: secret patterns in staged content.
# Use git diff --cached to scan only what's about to be committed.
diff_content="$(git diff --cached --no-color 2>/dev/null)"
if [ -n "$diff_content" ]; then
  # Find added lines (+) that match any secret pattern.
  matches="$(printf '%s' "$diff_content" | grep -E '^\+[^+]' | grep -E "$SECRET_PATTERNS" 2>/dev/null || true)"
  if [ -n "$matches" ]; then
    # Robust line count -- handles single-line matches without trailing newline.
    match_count="$(printf '%s\n' "$matches" | grep -c .)"

    # Identify which pattern types matched (for human-readable summary;
    # never echo actual secret values).
    types=""
    if printf '%s' "$matches" | grep -qE 'sk-ant-'; then types="${types}Anthropic "; fi
    if printf '%s' "$matches" | grep -qE 'sk-(proj-|admin-)?[A-Za-z0-9_-]{30,}'; then types="${types}OpenAI "; fi
    if printf '%s' "$matches" | grep -qE 'AKIA[0-9A-Z]{16}'; then types="${types}AWS "; fi
    if printf '%s' "$matches" | grep -qE 'AIzaSy[A-Za-z0-9_-]{30,}'; then types="${types}Google "; fi
    if printf '%s' "$matches" | grep -qE '(ghp|github_pat)_'; then types="${types}GitHub "; fi
    if printf '%s' "$matches" | grep -qE 'xox[baprs]-'; then types="${types}Slack "; fi
    if printf '%s' "$matches" | grep -qE 'rnd_[A-Za-z0-9]'; then types="${types}Render "; fi
    if printf '%s' "$matches" | grep -qE 'BEGIN .*PRIVATE KEY'; then types="${types}PrivateKey "; fi
    types="$(printf '%s' "$types" | sed 's/[[:space:]]*$//')"

    violations="${violations}  SECRET-PATTERN: ${match_count} line(s) match [${types}]
"
  fi
fi

if [ -n "$violations" ]; then
  cat >&2 <<EOF
========================================================
COMMIT BLOCKED: secret-hygiene.md violation
========================================================
$violations
This commit would push plaintext secrets to a remote. Per
~/.claude/rules/secret-hygiene.md:

  - Source of truth for credentials is 1Password (vault Amo Personal).
  - .env files at home root or matching forbidden filenames are not
    permitted under any project.
  - To unblock:
      a) Remove the secret from staged content (use op://... reference instead),
         OR rotate it first if already compromised.
      b) git reset HEAD -- <file>  # unstage
      c) Edit the file to use environment variables loaded from 1Password.
      d) Re-stage and re-commit.

Bypass (NOT RECOMMENDED -- only after rotating + verifying):
  git commit --no-verify

========================================================
EOF
  exit 1
fi

exit 0
