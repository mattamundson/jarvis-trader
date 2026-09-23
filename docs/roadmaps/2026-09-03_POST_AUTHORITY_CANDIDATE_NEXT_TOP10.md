# JARVIS Next Top-10 ROI Loop — 2026-09-03T04-40CDT

## Next-hour goal
Prepare the dashboard authority cutover so it can be executed with minimal runtime risk: preserve canonical-only artifacts, audit PM2 binding, and turn the verified authority candidate into an execution-ready cutover packet.

## Why this is #1
The hard part is no longer proving the code works. That is already done on the authority candidate. The remaining risk is operational cutover discipline.

Current evidence:
- canonical runtime on `:3010` is green and authenticated
- canonical Git authority is not trustworthy (`1939` status rows)
- authority candidate branch on merged master is verified (`install`, `tsc`, `build`, `Playwright` all passed)
- in-place canonical repair remains the wrong path

## Ranked top-10 ROI tasks
1. Capture the preservation inventory for canonical-only artifacts before any cutover. [RISK]
2. Audit the exact PM2 binding/working-directory assumptions for `jarvis-dashboard`.
3. Write the literal cutover command set and rollback command set, with no placeholders. [RISK]
4. Dry-run the authority candidate runtime on a non-production port using canonical auth/env inputs.
5. Record the cutover packet in `session_manifest.json`, `DASHBOARD_STATE.md`, and handoff.
6. Document the MES enabled/not-tradeable disagreement without changing behavior. [safety-review if behavior changes]
7. Promote state-db backup verification into recurring restore-certification evidence.
8. Convert deployed-auth smoke into a repeatable watchdog/evidence lane.
9. Clean contradictory MES status docs/memory so operator truth is singular.
10. Re-rank immediately after the cutover packet is complete.

## Strategy
1. Preserve first.
2. Audit supervisor bindings second.
3. Only then decide whether the next loop should execute cutover or stop at an execution-ready packet.
