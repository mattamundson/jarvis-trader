# GitHub Actions startup_failure evidence — 2026-09-11

Repository: `mattamundson/jarvis-trader`
Branch: `feat/ci-startup-diagnostics-20260911`
PR: https://github.com/mattamundson/jarvis-trader/pull/803

## Symptom

New pushes and pull-request events create Actions runs that complete as `startup_failure` before any job starts. The workflow name is empty and job count is `0`, so repository code and workflow steps did not execute.

## Fresh evidence

| Run ID | Event | Conclusion | Job count | Workflow name | URL |
|---:|---|---|---:|---|---|
| 34567897586 | push | startup_failure | 0 | empty | https://github.com/mattamundson/jarvis-trader/actions/runs/34567897586 |
| 34567925696 | pull_request | startup_failure | 0 | empty | https://github.com/mattamundson/jarvis-trader/actions/runs/34567925696 |
| 34569134274 | push | startup_failure | 0 | empty | https://github.com/mattamundson/jarvis-trader/actions/runs/34569134274 |

Historical comparison run from PR #787:

| Run ID | Event | Conclusion | Job count | URL |
|---:|---|---|---:|---|
| 33859218729 | pull_request/push context | startup_failure | 0 | https://github.com/mattamundson/jarvis-trader/actions/runs/33859218729 |

## Local verification already passed for diagnostic changes

- `python -m py_compile scripts/ci/collect_github_actions_startup_failure.py` → exit 0
- `python scripts/ci/collect_github_actions_startup_failure.py --help` → exit 0
- YAML parse of `.github/workflows/*.yml` → all parsed successfully
- Collector readback for `33859218729`, `34567897586`, `34567925696`, `34569134274` → JSON valid, conclusions captured
- New-file secret scan for token/private-key patterns → 0 matches

## Interpretation

This is not a failing JARVIS unit/build/test path. The failure occurs before checkout and before any shell step. Treat as GitHub Actions repository/account startup infrastructure, permissions/billing, or workflow-registration failure until GitHub provides a more specific server-side error.

## Support ticket payload

Attach the JSON files in this directory and cite the run IDs above. The minimum support question:

> Why do new Actions runs in `mattamundson/jarvis-trader` complete as `startup_failure` with empty workflow names and zero jobs before any workflow code starts?
