# Tape truthfulness — historical feature-base verification

Current-master acceptance and deviations: see `TAPE_MASTER_INTEGRATION_20261107.md`. This document preserves original PR1011 evidence only; its branch/override/test counts are not the current-master integration contract.

## Scope and ancestry
Stacked review candidate against published `dashboard/tape-20261103` at `b26d24bdefe3de7dbf173f0c194146aedbad951e`. Master `c35fdafbb26382076fae078eb5792f626aef8678` does not contain `/tape`; this is not a master-based integration or production deployment. Child implementation commit `a90e05932b8a1501103801813fcc3f0f23751131` plus parent correction is the review scope.

No engine, broker, risk/kill-switch, runtime env or serving-tree changes. All new route behavior is read-only. No orders or scheduler actions.

## Behavior verified
- Missing or stale actual ticks prevent trigger and analytical evaluation even if heartbeat/file timestamps are recent.
- Tick/heartbeat age is derived from producer `as_of_epoch`, not copied file mtime. Missing/future source clocks remain unknown.
- Sunday-evening Monday plans compare to Globex session date rather than Sunday calendar date; stale/wrong-session/conflicting plan sources remain unavailable for actionable triggers.
- No-data case says divergence not evaluated. Empty alert list does not claim full CVD/NQ agreement.
- Schedule states are explicitly schedule-based with holiday limitations, never inferred from recorder idleness.
- Plan overlays are withheld from active chart calculations when the plan or tick evidence is unavailable.

## Follow-through: both inherited failures repaired

The subsequent parent run in `reports/dashboard-parent-verification/20261107T182554Z` supersedes the initial unit failure status below: **358 tests,356 passed,0 failed,2 skipped**,exit0; typecheck/build exit0; fresh fixture Playwright8 passed,exit0. No new skips.

- Restored explicitly configured `TAPE_STATE_DIR/gates.md` discovery after higher-priority `HERMES_GATES_PATH`; blank values do not create a cwd lookup. Added precedence/blank-path tests.
- Corrected the SPX wiring oracle to follow the existing page → MissionControlLocal split, retain the card's enclosing error boundary and additionally forbid it from VercelGatesOnly. No product-side SPX change.
- Mutation test:positive control exit0; removing boundary,removing local return and leaking card reference into public view each exit1 as expected. No live source mutated.
- Independent narrow review PASS; no required corrections. Initial RED and base logs retained for provenance.

## Initial parent execution evidence (historical)
Executed in isolated `dashboard-parent-review/dashboard`; not against the production server.

| Gate | Actual result |
|---|---|
| `node node_modules/typescript/bin/tsc --noEmit` | exit 0 |
| Node focused tests: marketSession, tapePlanAvailability, routeManifest, tapeParentReview | 26 passed; exit 0 |
| `node node_modules/next/dist/bin/next build` | exit 0 |
| `node node_modules/@playwright/test/cli.js test --config=playwright.tape.config.ts` | 8 passed; exit 0 |
| Full Node unit suite | 357 tests: 353 passed, 2 failed, 2 skipped; exit 1 |

Two whole-suite failures were reproduced by executing the exact base blobs at `b26d24bd`: `hermesGatesBridge` candidate discovery and `spxIntradayApiContract` Mission Control source-mount assertion. Base probe: 7 tests, 5 passed, 2 failed, exit 1. No skip/assertion weakening applied. **This initial run was not green. The follow-through above repairs both failures; master integration and remote code verification still gate deployment.**

Playwright uses fresh port3014 with server reuse disabled, dedicated fixture input paths, no credentials, engine/master URLs pointed to closed loopback port9, API interception and WebSocket closure. It includes a real fixture-backed API transformation test. Synthetic fixtures are test inputs only, not claimed live market observations.

Durable local logs: recovery workspace `reports/dashboard-parent-verification/20261107T181053Z/{typecheck,unit,build,playwright}.log`, `receipt.json`, and `reports/dashboard-base-unit-probe/unit-baseline.log`.

## Independent review
Read-only reviewer verdict PASS with no must-fix issues, covering parent diff, fresh-tick gate, session-date wiring and test isolation. Review did not run tests; execution results above are parent-observed. Optional followups: explicit unknown-session kind when producer contract omits Globex date; threshold single-source consolidation. No global-green claim.

## Acceptance limits
Draft publication only. Stacked-base integration and exact-head remote checks must be resolved before merge/deploy. Inherited unit failures are now resolved locally; main code CI does not trigger on this feature-base draft. No market-data sufficiency, strategy edge, paper routing or live-capital authorization is inferred from these tests.
