# Plan — Market Brief Production Readiness: Base-Rate v1

## Finish line

Make the Market Brief production-ready within the defensible statistical scope established by the no-lookahead walk-forward study:

- publish the trailing unconditional base-rate probability block as the primary `ANALYSIS_ONLY` forecast;
- demote matched-state conditioning to a clearly labelled provisional diagnostic, not claimed edge;
- keep pre-registration/scoring/dead-man loops intact as prospective confirmation;
- verify with Python tests, dashboard tests, typecheck/build, and route/API smoke where feasible;
- avoid live trading, risk config, kill-switch, `.env`, broker, and DO_NOT_TRADE changes.

## Steps

1. Clean the worktree and branch from current `origin/master` after PR #911.
2. Patch `scripts/market_brief_base_rates.py` so `probabilities` is the trailing `__all__` base rate, with matched-state probabilities under `conditional_diagnostic` / `provisional` metadata.
3. Update tests for exact-100 base-rate publication and provisional conditional disclosure.
4. Update dashboard types/parser/card/tests so the UI says `BASE RATE` and shows conditional as `PROVISIONAL / NO MEASURED EDGE`.
5. Run gates: Python compile/ruff/tests, dashboard node test, TypeScript, build, targeted Playwright smoke.
6. Open/merge PR if local verification is clean and CI remains billing-blocked; deploy/cut over serving tree only after verified build.
7. Update operational handoff/skills with the new verdict so stale `state conditioning edge` language does not persist.
