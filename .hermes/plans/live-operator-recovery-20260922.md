# Live operator recovery loop — 2026-09-22

## Problem
User correctly reprioritized: a useful live/paper operator path outranks new analytics features. Current verified state: engine/dashboard are up and dashboard protected proxy auth was repaired, but `/pipeline/actionable` times out and recent pipeline decisions are not becoming fresh paper trades.

## Safety boundaries
- No live trading enablement.
- No kill-switch/risk config changes.
- No broker/order-routing changes without `[safety-review]`.
- MCL/MNQ are informational only; no operational trade actions.

## Finish line for this tranche
1. `/pipeline/actionable` returns fast and fails open with diagnostic counts.
2. Tests prove the actionable board does not hang and explains empty boards.
3. Live probes show protected dashboard proxy routes still return 200.
4. Report the current pipeline → queue → paper-trade gap quantitatively.

## Steps
1. Fix read path for recent approvals/actionable endpoint without altering execution behavior.
2. Add focused regression coverage for the route/DB read path.
3. Run targeted engine tests and lint for changed files.
4. Probe live endpoints through dashboard after restart if code changed.
