# JARVIS Runtime Hardening — Next Top 10 ROI Queue

_Last updated: 2026-09-03 00:14 CDT_

## Goal

Convert the recovered green runtime into a reproducible, operator-truthful, low-drift service state: durable evidence, explicit contradictions, stable PM2 supervision, and a safe path to restore canonical Git/VCS truth.

## Strategy

1. Resolve truth asymmetry first: runtime is green, but canonical Git metadata is broken.
2. Preserve operator truth in durable artifacts before attempting any VCS repair.
3. Keep safety-sensitive runtime config review separate from service-operability work.
4. Prefer read-only diagnostics before any structural repair of the canonical tree.

## Top 10 highest-ROI tasks

1. Diagnose canonical repo `.git` metadata breakage read-only.
2. Design an archive-safe VCS recovery plan for the canonical runtime tree.
3. Observe PM2 stability/restart deltas after the new app set.
4. Promote runtime-evidence bundle usage into operator docs/runbooks.
5. Create a compact incident severity summary from runtime snapshot contradictions.
6. Persist a rolling runtime-evidence archive for future comparisons.
7. Write an external HTTPS verification runbook snippet for non-local probes.
8. Stage a dedicated `[safety-review]` follow-up for runtime env provenance.
9. Define a clean-lane execution boundary for future git repair work.
10. Re-rank the next ROI queue after git-state truth is known.

## Recommended immediate action

Start with item #1 now: inspect `C:/Users/mattm/ThinkorSwim/jarvis-trader/.git` read-only to determine whether the canonical runtime tree is a broken worktree pointer, truncated directory, or mismatched clone metadata. Do not mutate anything until the failure class is proven.

## Diagnosis outcome

- Failure class proved: the canonical runtime tree has a **truncated `.git` directory**.
- Read-only inspection found:
  - `.git` exists and is a directory
  - `.git` contains only `config`
  - `.git/HEAD` is missing
  - `.git/commondir` is missing
  - `.git/gitdir` is missing
- Conclusion: this is neither a valid normal clone nor a valid worktree pointer; CLI Git failure is expected.

## Archive-safe recovery strategy

1. Do **not** repair Git metadata in place on the serving runtime tree while PM2 is using it.
2. Archive the broken `.git` directory before any future repair attempt.
3. Use a **clean separate lane** (fresh clone/worktree) for all VCS operations and code review.
4. Treat the canonical runtime tree as a serving tree first, not as the authoritative Git workspace, until VCS metadata is rehydrated in a dedicated follow-up lane.
5. Keep runtime evidence artifacts (`docs/session-logs/*`, archived JSON evidence) as the continuity source between now and the VCS repair.
