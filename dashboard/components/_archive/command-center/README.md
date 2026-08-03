# Orphaned command-center components — archive index

Dashboard components under `command-center/` that are **not imported by any route** (confirmed via
repo-wide `git grep`, including `dashboard/app/**`) and are excluded from the TypeScript build
(`dashboard/tsconfig.json` → `exclude: ["components/_archive/**"]`). Retained for reference only —
**do not re-mount without fixing the known defects below.**

| Module | Why archived |
|--------|--------------|
| `tabs/OverviewTab.tsx` | Unmounted (no importer). Also carries an inverted instrument APPROVED/HALTED table (MCL/MNQ APPROVED, MGC HALTED) that contradicts engine truth (`engine/backtest/signals.py` `DO_NOT_TRADE_SYMBOLS = {MCL, MNQ, M2K}`; the live-traded pair is MES/MGC). Backlog item D2-05. |
| `tabs/AnalyticsTab.tsx` | Unmounted (no importer). Same inverted instrument-status table as `OverviewTab.tsx`. Backlog item D2-05. |
| `tabs/AuditTab.tsx` | Unmounted (no importer). Same inverted instrument-status table as `OverviewTab.tsx`. Backlog item D2-05. |
| `tabs/TradingTab.tsx` | Unmounted (no importer). Archived alongside the above because it is the sole importer of `PipelineFlowDiagram.tsx`. |
| `PipelineFlowDiagram.tsx` | Unmounted outside this archive (only `tabs/TradingTab.tsx` imported it, and that file is itself unreachable from any route). |

## How this was verified

`git grep -n "OverviewTab\|AuditTab\|AnalyticsTab\|TradingTab\|PipelineFlowDiagram" -- dashboard/app`
returned zero hits before the move — no page or layout under `dashboard/app/**` imports any of these
five components, directly or transitively. The live, correctly-oriented instrument-status table ships
from `dashboard/app/command-center/constants.ts` via `dashboard/app/command-center/page.tsx`, which is
unrelated to this archived tree.

## Reviving a component from here

1. Fix the inverted status literals first (MES=APPROVED, MGC=APPROVED, MCL=HALTED, MNQ=HALTED) if the
   file is one of the three tab components listed above.
2. Remove its entry from this table.
3. Move it back out of `_archive/` and remove the corresponding `tsconfig.json` exclusion if nothing
   else remains archived.
4. Wire it into an actual route under `dashboard/app/`.
