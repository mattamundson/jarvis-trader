# CI startup diagnostics next-top queue — 2026-09-11

Ranked by risk-adjusted ROI for restoring trust in GitHub checks without touching live trading behavior.

| Rank | Item | Expected value | Safety boundary | Status |
|---:|---|---|---|---|
| 1 | Add `CI Startup Canary` workflow | Separates GitHub startup health from app/test failures | CI only | In progress |
| 2 | Add sanitized Actions evidence collector | Makes support/debug bundles reproducible | Metadata only, no secrets | In progress |
| 3 | Add runbook with startup_failure decision tree | Prevents false code-failure diagnosis | Docs only | In progress |
| 4 | Push diagnostic PR and observe first canary run | Confirms whether startup issue persists | No force-push | Pending |
| 5 | If blocked, attach evidence to PR comment | Preserves machine-readable failure context | No secrets | Pending |
| 6 | Add canary result to future dashboard ops digest | Continuous detection | Report-only | Pending |
| 7 | Add branch-hygiene note for dirty local authority branch | Prevents cross-lane contamination | Docs only | Pending |
| 8 | Retire temporary empty rerun branch after verifying preservation | Reduces branch noise | Archive/preserve before remove if needed | Pending |
| 9 | Consolidate CI startup rules into verification skill if new gap found | Makes process durable | Skill patch only if evidence proves gap | Pending |
| 10 | Re-run PR #783/#797 checks after GitHub account/billing state is fixed | Restores merger confidence | No safety-review auto-merge | Externally blocked |
