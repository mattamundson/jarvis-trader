# JARVIS Trader Dashboard — Final Status (2026-06-12)

Project: complete the dashboard so every feature, strategy, backtest, number,
live chart, and data feed is complete, correct, honest, and online 24/7.

## Build & typecheck

- `tsc --noEmit` → **0 errors** (run after every story).
- `pnpm build` (Next.js 15.5) → **Compiled successfully in 27.0s, 0 errors**, BUILD_ID written. ✅

## Stories

| Story | State | Notes |
|---|---|---|
| US-001 Deploy trade-review loop | **AMO-GATED** | PRs #52 + #54 need Amo's `[safety-review]` tag (touch main.py/risk/) → merge → restart. Code ready. |
| US-002 Chart on trade review | ✅ done (50c2c3b) | Candlestick + entry/exit markers + stop/target lines on /trades/[id]/review. |
| US-003 Audit unexamined pages | ✅ done (c48c06f) | 12 pages audited; 3 real crash risks fixed; 9 clean. |
| US-004 De-static dishonest data | ✅ done (f06100f) | data-integrity fake-green + discord frozen count fixed; performance/scorecard already honest. |
| US-005 Chart on /analysis | ✅ done (b88def1) | 15m live chart after pipeline run. |
| US-006 24/7 reliability | ✅ verified (0bfa8ed) | 4 services online, save done; boot-resurrect task = Amo command in RELIABILITY.md. |
| US-007 Monitoring verification | ✅ verified (0bfa8ed) | Watchdogs recent+green; /health honest re IB; surfaced DataIntegritySentinel failing. |
| US-008 Remote access | ✅ verified (45095ec) | Tailnet-reachable now at http://100.68.247.106:3010; serve+cloudflare documented. |
| US-009 Unified command pane | ✅ done (989e3ca) | Added live chart to /command-center (had health/P&L/positions/signals/edge). |
| US-010 Final build + STATUS | ✅ done | This doc; build + tsc green. |

**All non-AMO-gated stories pass.** Only US-001 (merge/deploy) remains, gated on Amo's safety-review tag.

## Per-page classification (36 routes)

LIVE (fetch real engine data, honest empty/error states):
`/` (root cockpit), `/command-center`, `/analysis`, `/backtest`, `/health`,
`/portfolio`, `/scorecard`, `/performance` (snapshot-labelled + live link),
`/strategies`, `/strategy-c`, `/strategy-ledger`, `/validation`, `/watchlist`,
`/trades`, `/trades/[id]/review`, `/trades/journal`, `/trades/pending-approvals`,
`/journal`, `/journal-review`, `/options`, `/paper`, `/parallel-paper`,
`/kairos`, `/crypto`, `/polymarket`, `/config`, `/settings`, `/data-integrity`,
`/jarvis`, `/master`, `/master/trading`, `/master/finances`.

STATIC SHELL (tab controllers delegating to live child widgets):
`/learning`, `/stats`, `/discord`.

EMBED/STUB: `/strategy-c-command` (iframe to a static HTML cockpit).

## Crash-guard fixes landed (US-003)

- `kairos`: `dream.severity_counts?.*` + `(dream.top_watchers ?? [])`.
- `parallel-paper`: `EquitySparkline` guards `!data ||` before `.length`.
- `strategy-c`: shape-guard on `signal.layers.{momentum,vol,vix,macro}` + `holdings`
  → honest "incomplete payload" message instead of a crash.

## Honesty fixes landed (US-004)

- `data-integrity`: hardcoded green "CONNECTED/ACTIVE" → neutral "CONFIGURED"
  + caption pointing to /health.
- `discord`: removed frozen "281,838 signals" claim.

## Live charts added

- `/trades/[id]/review` — entry/exit markers + stop/target lines (US-002).
- `/analysis` — 15m chart for the analyzed symbol (US-005).
- `/command-center` — 15m chart with per-instrument selector (US-009).
- All reuse the one `components/command-center/charts/CandlestickChart.tsx`
  (extended with `markers` + `priceLines` props) and `lib/api.ts fetchBars`.

## Outstanding (for Amo)

1. **US-001 deploy** — tag PRs #52 + #54 `[safety-review]`, merge to master, update
   the running checkout, restart engine; then /strategy/ledger +
   /trades/{id}/full-review go live (currently 404 on the running engine).
2. **pm2 boot persistence** — run the `Jarvis-PM2-Resurrect` logon-task command
   (RELIABILITY.md) so services survive reboot.
3. **`Jarvis-DataIntegritySentinel` failing** (LastTaskResult=1) — investigate.
4. **IB data leg dark** — the PR #34 clientId fix needs an engine restart to apply.
5. Optional: `tailscale serve --bg 3010` for HTTPS phone access (REMOTE-ACCESS.md).

This branch (`feat/dashboard-completion`) contains US-002→US-010. No engine
safety files touched here → this dashboard PR does **not** need a safety-review tag
(that requirement is on the separate #52/#54).
