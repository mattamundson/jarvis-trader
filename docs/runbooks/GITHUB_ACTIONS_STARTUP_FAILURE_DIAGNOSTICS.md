# GitHub Actions startup_failure diagnostics

Use this runbook when a JARVIS PR or workflow reports `startup_failure`, jobs show zero useful steps, or `gh run view --log` returns `log not found`.

## Safety boundary

This runbook is CI/tooling only. Do **not** change live trading, risk settings, kill-switch logic, broker routing, `.env`, or halted-symbol gates while diagnosing Actions startup. Any engine/risk/kill-switch change still requires a dedicated `[safety-review]` PR.

## Fast interpretation

`startup_failure` before checkout means repository code did not execute. Treat it differently from a failed test:

| Signal | Interpretation |
|---|---|
| `conclusion=startup_failure` and job count is 0 | GitHub could not start the workflow/job; repo code did not run. |
| jobs exist but first step failed before checkout | runner image, permissions, marketplace action, or shell setup issue. |
| checkout completed and tests failed | normal code or test failure; use normal CI triage. |
| `gh run view --log` says `log not found` | common for pre-step startup failures; collect API evidence instead. |

## Evidence collector

From the repository root:

```bash
python scripts/ci/collect_github_actions_startup_failure.py \
  --repo mattamundson/jarvis-trader \
  --branch master \
  --limit 20 \
  --output diagnostics/github-actions-startup-evidence.json
```

For a known run:

```bash
python scripts/ci/collect_github_actions_startup_failure.py \
  --repo mattamundson/jarvis-trader \
  --run-id <RUN_ID> \
  --output diagnostics/github-actions-run-<RUN_ID>.json
```

The collector stores sanitized run/job/workflow metadata only. It does not read secrets or workflow environment values.

## Canary workflow

The `CI Startup Canary` workflow exists to answer one question: can GitHub start a trivial workflow in this repository?

Expected healthy result:
1. `pre-checkout runner marker` appears in logs.
2. checkout succeeds.
3. `CANARY_REPOSITORY_CONTENT_OK=1` appears.
4. marker artifact uploads.

If the canary itself returns `startup_failure`, then editing app code, test code, or the main CI workflow is not the primary fix. Escalate as GitHub Actions account/repository startup infrastructure.

## Escalation ladder

1. Collect run evidence with the script above.
2. Check repo-level Actions permissions:
   ```bash
   gh api repos/mattamundson/jarvis-trader/actions/permissions
   ```
3. List active workflows:
   ```bash
   gh api repos/mattamundson/jarvis-trader/actions/workflows
   ```
4. Trigger the canary manually when available:
   ```bash
   gh workflow run "CI Startup Canary" --ref master
   ```
5. Read back the newest canary run:
   ```bash
   gh run list --workflow "CI Startup Canary" --limit 5
   gh run view <RUN_ID> --json status,conclusion,jobs,url
   ```
6. If canary and real workflows both fail before steps, create a GitHub Support evidence pack with:
   - affected repo
   - run IDs
   - `startup_failure` conclusions
   - zero-job/zero-step evidence
   - permissions/workflows API payloads
   - note that local verification passed for the relevant PR/commit

## Known JARVIS context

- `JARVIS TRADER CI` failures on PR #787 and later PRs showed `startup_failure` with no code-execution logs.
- Local dashboard verification for PR #787 passed after merge: unit, typecheck, component, Playwright SPX smoke, and `build:clean`.
- Do not interpret absent GitHub logs as test failure unless a job actually started and produced a failing step.
