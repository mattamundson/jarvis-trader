# CI closeout + hygiene loop

Finish line: master remains green, merged repair branches are archived/cleaned safely, and the recurring checkout git warning is either fixed by a PR with green checks or explicitly blocked.

## Steps
1. Verify current master CI and Pre-Deploy are green on the same SHA.
2. Archive merged repair branch refs before deleting local/remote stale branches.
3. Diagnose the `git submodule foreach` checkout warning.
4. If the warning fix is safe and non-risk-config, open a PR and watch checks to completion.
5. Write a durable handoff with exact git state and next action.

## Safety boundaries
- No live engine/risk/kill-switch config changes.
- No direct push to master.
- Archive branch refs before removing stale local/remote branch names.
