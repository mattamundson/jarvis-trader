# CI startup diagnostics + canary plan

Finish line: produce a clean, reviewable JARVIS PR that adds a zero-risk GitHub Actions startup canary, a CLI evidence collector, and an operator runbook; verify all new files locally and collect remote startup evidence after push.

## Scope
- Safe CI/docs/tooling only.
- No engine runtime, risk config, kill-switch, broker, `.env`, or symbol-gate edits.
- Preserve existing dirty `engine/*` work in the separate authority worktree untouched.

## Steps
1. Use clean worktree `C:/Users/mattm/ThinkorSwim/wt-jarvis-ci-startup-diagnostics-20260911` on `feat/ci-startup-diagnostics-20260911`.
2. Add `.github/workflows/ci-startup-canary.yml` with manual + scheduled + push triggers and explicit pre-checkout marker steps.
3. Add `scripts/ci/collect_github_actions_startup_failure.py` to collect sanitized run/job/workflow/status evidence through `gh api`.
4. Add `docs/runbooks/GITHUB_ACTIONS_STARTUP_FAILURE_DIAGNOSTICS.md` with the escalation ladder and exact commands.
5. Verify: YAML parse, `python -m py_compile`, script `--help`, dry-run collection against known run `33859218729`, git diff scope.
6. Commit, push branch, open PR, trigger/observe canary if GitHub accepts it.
7. Update handoff and report PASS/PARTIAL/BLOCKED with exact evidence.
