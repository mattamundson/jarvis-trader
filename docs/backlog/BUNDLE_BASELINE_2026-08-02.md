# Bundle Baseline — 2026-08-02 (Wave 4, P5-1)

Trustworthy First-Load-JS baseline for the dashboard route table, per Plan Phase 5.1.
Every pre-existing number in prior docs predates the understanding of the
static-import-defeats-`dynamic()` defect class (see Phase 0.2 `/backtest` fix), so
those numbers are not trusted as a comparison basis. This is a fresh measurement.

**How measured:** `pnpm run build:clean` (removes `.next`, then `next build`), run
against the `feat/dashboard-phase-drain` worktree tree as of this task (includes
whatever routes/components peer wave-4 agents had already landed or had in-flight
in the shared worktree at measurement time — this is a point-in-time snapshot, not
a snapshot of a single commit). Build was run from an isolated copy of the
`dashboard/` source tree (source files copied out, `node_modules` junctioned back
in) to avoid a shared `.next` output-directory race with the several other wave-4
agents building concurrently in this same worktree — direct in-place
`pnpm run build:clean` runs failed 3/3 times with `ENOENT` on `.next/server/**/*.nft.json`
and `.next/types/**/*.ts` from concurrent deletion/regeneration of `.next` by peer
agents. The isolated build reads the same source files, so the numbers are accurate
for the tree at that moment.

Next.js 15.5.14. `○` = static, `ƒ` = dynamic (server-rendered on demand).

```
Route (app)                                 Size  First Load JS
┌ ○ /                                      163 B         103 kB
├ ○ /_not-found                            163 B         103 kB
├ ○ /analysis                            8.49 kB         130 kB
├ ƒ /api/amo/[...path]                     163 B         103 kB
├ ƒ /api/engine/[...path]                  163 B         103 kB
├ ƒ /api/fleet                             163 B         103 kB
├ ƒ /api/master/[...path]                  163 B         103 kB
├ ○ /atr-trail                           5.17 kB         175 kB
├ ○ /backtest                            9.85 kB         134 kB
├ ○ /command-center                      20.3 kB         141 kB
├ ○ /config                               4.5 kB         110 kB
├ ○ /crypto                              3.33 kB         114 kB
├ ○ /dashboard                             163 B         103 kB
├ ○ /data-integrity                      3.37 kB         121 kB
├ ○ /discord                             4.24 kB         112 kB
├ ○ /framing-brief                       2.54 kB         114 kB
├ ○ /health                                14 kB         135 kB
├ ○ /hidden-pivots                       5.51 kB         127 kB
├ ○ /jarvis                              12.1 kB         133 kB
├ ○ /journal                             3.38 kB         127 kB
├ ○ /journal-review                      7.22 kB         122 kB
├ ○ /kairos                              7.28 kB         129 kB
├ ○ /learning                            7.55 kB         125 kB
├ ○ /master                              4.84 kB         116 kB
├ ○ /master/finances                     3.08 kB         114 kB
├ ○ /master/trading                         3 kB         114 kB
├ ○ /mission-control                     7.08 kB         128 kB
├ ○ /options                             3.42 kB         114 kB
├ ○ /paper                               20.2 kB         144 kB
├ ○ /parallel-paper                      5.81 kB         117 kB
├ ○ /performance                         36.3 kB         222 kB
├ ○ /pipeline-board                      3.48 kB         121 kB
├ ○ /polymarket                          3.82 kB         118 kB
├ ○ /portfolio                           4.75 kB         116 kB
├ ○ /regime                               116 kB         234 kB
├ ○ /research-log                        6.96 kB         131 kB
├ ○ /scorecard                           15.4 kB         145 kB
├ ○ /screener                             4.8 kB         121 kB
├ ○ /settings                            10.2 kB         128 kB
├ ○ /signal-outcomes                     5.02 kB         123 kB
├ ○ /signals                             5.96 kB         124 kB
├ ○ /stats                                 163 B         103 kB
├ ○ /strategies                          17.3 kB         139 kB
├ ○ /strategy-c                          6.76 kB         123 kB
├ ○ /strategy-c-command                    163 B         103 kB
├ ○ /strategy-ledger                     4.72 kB         126 kB
├ ○ /strategy-research                   2.87 kB         124 kB
├ ○ /thinkscript                         5.85 kB         127 kB
├ ○ /today                                7.9 kB         119 kB
├ ƒ /trades                              2.64 kB         126 kB
├ ƒ /trades/[id]/review                  5.26 kB         126 kB
├ ƒ /trades/journal                        163 B         103 kB
├ ƒ /trades/pending-approvals             8.9 kB         130 kB
├ ○ /trading-eligibility                 2.73 kB         124 kB
├ ○ /trust-pane                            13 kB         131 kB
├ ○ /validation                          30.8 kB         201 kB
├ ○ /vault                               4.41 kB         122 kB
└ ○ /watchlist                           14.3 kB         132 kB
+ First Load JS shared by all             103 kB
  ├ chunks/3688-17a440d6d731e51c.js        46 kB
  ├ chunks/d9681acb-af73fb2414308dda.js  54.2 kB
  └ other shared chunks (total)          2.56 kB
```

## P5-1 finding: `/validation` double-import defect not present

The spec for P5-1 called for removing a dead static import at
`app/validation/page.tsx:41-44` that duplicates a `dynamic()` call below it (same
defect class as the `/backtest` fix in Phase 0.2). On inspection, `app/validation/page.tsx`
contains **no `dynamic()` calls at all** — every widget it mounts (`PipelineRunHistory`,
`PositionSizingCalculator`, `ReconciliationWidget`, `ExportDataWidget`,
`WFEMonitorWidget`, `TradingDaysCountdownCard`, `BacktestVsPaperWidget`,
`ValidationChecklist`, `GoLivePlanCard`, `InstrumentEligibilityCard`, `PortfolioPLChart`,
`MESRevalidationTracker`, `MESForwardRecorderPanel`) is a plain static import. There is
therefore no dead static import to remove — the type-only imports the spec's line range
pointed at (`ValidationReport`, `CompareToBacktestResponse`, `ApprovedPaperGatesResponse`)
are already narrowed to `import type` (line 28).

Verified against the actual Phase 1.4 CI guard rather than by inspection alone:
`node scripts/check-guards.mjs` → `OK no-dynamic-import-defeated-by-static (0 violations)`
across the whole dashboard, confirming the guard is live and finds nothing here (or
anywhere else in the tree). The guard would have caught this defect class had it existed.

**Conclusion:** no code change was made to `app/validation/page.tsx` — there was nothing
to fix. `/validation` First Load JS is unchanged: **201 kB before, 201 kB after**
(30.8 kB route-specific + shared). `/validation` remains the 2nd-heaviest route after
`/regime` (234 kB) and `/performance` (222 kB) — it is a real optimization candidate
(13 statically-mounted widgets, zero code-splitting), but converting it to `dynamic()`
imports is a materially larger change than the "dead duplicate import" defect this task
was scoped to, so it was left for a follow-up rather than done unscoped here.

## P5-3: /analysis, /trades/[id]/review, /today

Same defect-class check as P5-1: none of these 3 routes had any `dynamic()` call being
negated by a static import — `/analysis` had exactly one pre-existing `dynamic()`
(`PriceTerrain3D`, correctly deferring three.js) and no defect; `/today` and
`/trades/[id]/review` had zero `dynamic()` calls to begin with. So this was purely the
"genuinely missed `next/dynamic` opportunity" branch of the spec, not the double-import
defect class.

All three routes statically imported a `lightweight-charts`-backed chart component that
is only meaningful after client-side data has loaded (`PriceChartPanel` on `/analysis`,
`CandlestickChart` directly on `/trades/[id]/review`, `MarketChart` on `/today`) —
`/trades/[id]/review` additionally statically imported `ExcursionPanel` and
`EntryTimingScenarios`, both gated behind `Boolean(t.symbol)` at render time (i.e. dead
weight until the trade record itself has loaded). Converted all of these to
`next/dynamic(..., { ssr: false, loading: () => <skeleton /> })`, mirroring the existing
`PriceTerrain3D` pattern already on `/analysis`.

**Measurement note:** `pnpm run build` in the shared worktree `dashboard/` directory was
racing several other wave-4 agents' concurrent builds against the same `.next` output
dir (confirmed via `Get-CimInstance Win32_Process` — 3+ concurrent `next build`/
`build:clean` processes at once) and failed with `ENOENT` (`.next/types/**`,
`.next/diagnostics/framework.json`) twice in a row. Switched to the same isolated-build
approach P5-1 used independently: source copied to a scratch dir, `node_modules`
junctioned back in, built there to avoid the shared `.next` race.

Before (measured pre-change, in-place build, before the `.next` race was diagnosed —
this one build completed cleanly prior to peer agents piling on) vs. after (isolated
build, matches the P5-1 table above exactly for these 3 routes since both were measured
against the same post-fix tree state):

| Route | Before | After | Delta |
|---|---|---|---|
| `/analysis` | 189 kB | 130 kB | **-59 kB (-31%)** |
| `/today` | 177 kB | 119 kB | **-58 kB (-33%)** |
| `/trades/[id]/review` | 183 kB | 126 kB | **-57 kB (-31%)** |

Shared First Load JS baseline (103 kB) was identical before and after, confirming these
are real per-route deltas, not build noise. All three exceeded the plan's own
measurable-benefit stop rule (Phase 5.3), so all three changes were kept — no revert
needed on this task. Commit: `c0fc3c2`.
