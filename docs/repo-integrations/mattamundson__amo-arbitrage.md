# amo-arbitrage → jarvis-trader dashboard integration proposal

**Date:** 2026-07-16
**Source system:** `mattamundson/amo-arbitrage` (private repo; local checkout `C:/Users/mattm/Code/amo-arbitrage`)
**Live deploy analyzed:** https://amo-arbitrage.vercel.app/#/ (Vite/React SPA on Vercel) + FastAPI backend on Railway (`amo-arbitrage-production.up.railway.app`) + Supabase
**Method:** Full source read of both repos (amo frontend `frontend/client/src/`, amo backend `backend/`, jarvis `dashboard/` + `engine/routers/`), cross-referenced against the 2026-07-10 dashboard audit and the 2026-07-09 CROSS_SIGNAL spec.
**Verification level:** static source analysis only — no proposal below has been implemented or runtime-verified.

---

## 0. Where the code lives (the "file explorer" answer)

The amo-arbitrage site is **not** part of jarvis-trader. It is its own repo:

| Piece | Location |
|---|---|
| Local checkout | `C:/Users/mattm/Code/amo-arbitrage` (per `scripts/ralph/prd.json` notes) |
| Frontend (the Vercel page) | `amo-arbitrage/frontend/client/src/` — Vite + React 18, wouter hash routing, TanStack Query, Zod, shadcn/ui |
| Backend | `amo-arbitrage/backend/` — FastAPI :8000, APScheduler pipelines, Supabase |
| Existing jarvis touchpoints | `dashboard/lib/amo-api.ts`, `dashboard/app/api/amo/[...path]/route.ts` (GET-only proxy), Trust-Pane AMO column (`dashboard/app/trust-pane/page.tsx`), `engine/integrations/amoarb_signals.py` → `/brief/session` advisory block, `engine/backtest/family_fdr.py` (ported from amo's `seasonals._bh_fdr`) |

## 1. What the site is, in one paragraph

An 11-commodity (grains/livestock/energy) research platform whose defining feature is an **honesty layer**: every number is labeled by provenance (backtest / paper / live / simulated / signal), every page is structurally split **validated vs exploratory**, position sizing is *withheld* until a strategy both survives a frozen pre-registered BH-FDR gate (q=0.10, m=5, tamper-hashed) **and** graduates a forward test (≥20 closed paper trades, forward PF > 1), and every emitted setup is later scored against what actually happened (hit/stop/expired, MFE/MAE, 1/3/5/10-day P&L). The UI is the thin, consistent rendering of that contract.

Route map (hash-routed; nav groups are literally "Validated", "Research & Exploratory", "Reference & System"): `/` dashboard, `/brief`, `/daily-edge`, `/actionable-now`, `/targets`, `/forward-test` | `/signals`, `/seasonal(+3d)`, `/cot`, `/weather`, `/spreads`, `/options(+3d)`, `/monte-carlo(+3d)`, `/research` | `/ops`, `/prices`, `/signal-outcomes`, `/methodology`, `/feed-health`, `/status`, `/settings`.

## 2. Constraints this proposal honors

- **Advisory-only invariant** (CROSS_SIGNAL spec, 2026-07-09): amo data may be *displayed* in jarvis, but must never feed a jarvis trade/risk/fund decision. Everything below is display/analytics-layer.
- **No safety-file changes**: nothing here touches `engine/config.py`, `engine/risk/`, or kill-switch code. If a later implementation does, it needs `[safety-review]`.
- **Badge variants are strict** (`bull|bear|warn|info|neutral|live|static`): amo-style provenance labels must be built as a *new component* (like amo's `ResultLabel`), not by adding badge variants.
- **`fetchEngine`/`postEngine` + `fetchAmo` only** — no bare fetches.
- **Reuse before build** (jarvis-search-discipline): several "gaps" are actually already-built-but-unmounted jarvis components; those are flagged as mount-not-port.

---

## 3. Ranked proposals

Effort: S = hours, M = a session, L = multi-session. Every item lists the amo source to crib from and where it lands in jarvis.

### Tier 1 — Trade predictions (the explicit ask)

#### P1. Signal-outcome scoreboard: "did our predictions pay off?" — **the single highest-value port**
- **What amo does:** every emitted setup is snapshotted (`backend/pipelines/signal_outcomes.py`: SNAPSHOT phase), then ≥10 days later scored (EVALUATE phase): `hit ∈ {target1_hit, target2_hit, stop_hit, expired, open}` by walking post-entry OHLC chronologically, plus `mfe_pct`/`mae_pct`, `price_1d/3d/5d/10d`, `hypothetical_pnl_pct`, and `regime_at_entry` attribution. Aggregated to hit-rate, avg P&L, per-commodity and **per-regime** breakdowns ("did the setup work or did the regime?"). UI: `SignalOutcomesPage.tsx` — summary card + expandable table + entry-timing what-if panel + CSV export.
- **Jarvis gap (confirmed):** **no signal-vs-outcome view is mounted anywhere.** `SignalAccuracyWidget` only computes direction win-rate from closed trades. The engine endpoints that would power a real one exist but are unsurfaced: `/analytics/signal-quality` (typed in `api.ts`, zero consumers), `/analytics/calibration` (only consumer `ConfidenceGauge.tsx` is unmounted), `/analytics/pipeline/confidence-stats` (unsurfaced). Jarvis pipeline output already carries entry/stop/T1 (S3 Trader stage), so the raw material for outcome scoring exists.
- **Proposal:** (a) dashboard: new `/signal-outcomes` page mounting `ConfidenceGauge` + a new outcomes table fed by `/analytics/signal-quality`; (b) engine: a `signal_outcomes`-style evaluator over recorded pipeline decisions (check overlap with `engine/analytics/outcome_hygiene.py` and `engine/backtest/forward_test.py` first — partial machinery exists). Point-in-time discipline applies: outcomes are evaluation targets only, never same-bar inputs.
- **Effort:** M (dashboard) + M (engine evaluator). **Value: highest.** This is the calibration feedback loop the system currently lacks a window into.

#### P2. "Actionable Now" live setup board for jarvis's own signals
- **What amo does:** `ActionableNowPage.tsx` + `backend/routers/actionable.py::derive_actionable` — each active setup becomes a live card: 7-state status chip (`awaiting_entry / triggerable / triggered / target_reached / invalidated / expired / unknown`, derived purely from latest price vs levels, entry zone = 0.25·ATR), **distance-to-entry in %, ATR, and ticks**, `planned_rr`, live `current_r` (R-multiple), notional per contract, age. 60s refresh.
- **Jarvis gap:** entry/stop/target exist in many response types (`MGCSignalResponse`, `PendingSignal`, S3 Trader stage) but no page answers "which signal is *actionable right now* and how far is price from the trigger?" — the closest is scattered across `/watchlist`, `/paper`, and command-center widgets.
- **Proposal:** engine: small pure `derive_actionable()` (crib the status-priority logic verbatim — it's ~120 lines of pure functions) exposed at e.g. `GET /pipeline/actionable`; dashboard: a board page or a command-center strip. Display-only; no order routing.
- **Effort:** M. **Value: high** — turns stored predictions into a glanceable "what do I do now" surface, which is exactly what Matt trades from.

#### P3. Deepen the amo advisory feed (more amo data in jarvis)
- **What exists:** Trust-Pane AMO column shows health + edge-verdict + jobs; `/brief/session` carries `prob_up/ic_overall/win_rate_oos`.
- **What amo now serves that jarvis doesn't display** (all GET, already reachable through the existing `app/api/amo/[...path]` proxy — zero amo-side changes): `/api/targets` (entry/stop/targets + quality grade + validation status), `/api/actionable` (live board), `/api/signal-outcomes/aggregate` (hit-rate — answers "should I trust amo's numbers at all"), `/api/scoreboard` (backtest-vs-forward PF per strategy), `/api/regime` (per-commodity vol/trend/COT/seasonal/IV strip), `/api/morning-brief` (5-pillar convergence).
- **Proposal:** extend `lib/amo-api.ts` with typed fetchers + extend the Trust-Pane AMO column (or a dedicated `/amo` page) with: outcomes hit-rate card, scoreboard mini-table, top-3 actionable setups. Keep the existing honest "signal-only, no execution" note. Advisory-only, GET-only proxy unchanged.
- **Effort:** S–M. **Value: high, cheap** — it's pure display over endpoints that already exist.

### Tier 2 — The honesty layer (amo's best structural idea)

#### P4. `ResultLabel` provenance badges for performance numbers
- **What amo does:** `components/ResultLabel.tsx` — a tiny badge on every performance figure: `backtest / paper / live / simulated / signal`, each with a hover hint. Universal answer to "what kind of number am I looking at?"
- **Jarvis gap:** the Trust Pane solves *data* provenance (live/stale/static feeds) but nothing labels *result* provenance — the scorecard, performance, and backtest pages mix backtest PF, paper P&L, and simulated numbers with no per-figure tag. Given the project's own verification-discipline memory (confidently-wrong numbers are worse than downtime), this is squarely on-mission.
- **Proposal:** new `dashboard/components/ResultLabel.tsx` (do NOT extend badge variants), applied first to `/scorecard`, `/performance`, `/backtest`, `/validation`.
- **Effort:** S. **Value: high trust-per-line-of-code.**

#### P5. Validated-vs-exploratory structure (nav groups + banner + de-emphasis)
- **What amo does:** one source of truth (`lib/nav.ts`) drives sidebar groups ("Validated" / "Research & Exploratory" / "Reference & System"), an `ExploratoryBanner` on every research page, validated cards always sorted above an exploratory divider, and unvalidated cards rendered `opacity-60 grayscale`.
- **Jarvis gap:** the sidebar groups by *topic* (Trading/Analysis/…), not by *evidence status*. `/strategies` (RL Lab), `/strategy-research`, `/kairos`, `/polymarket`, `/hidden-pivots` sit visually equal to validated MES/MGC surfaces.
- **Proposal:** add an `exploratory: true` flag to jarvis's nav model + an `ExploratoryBanner` component; de-emphasize unvalidated strategy cards on `/strategy-ledger`. No routing changes.
- **Effort:** S–M. **Value: medium-high** — it encodes "not validated" so it can't be forgotten under time pressure.

#### P6. Evidence-to-live graduation gate + strategy scoreboard (mount-not-port, mostly)
- **What amo does:** `EvidenceToLiveGate.tsx` (progress bar `evidence_gathered/evidence_target`, "ready" only when the backend says `graduation_ready`) + `StrategyScoreboard.tsx` (backtest screen **beside** live forward record: forward PF vs backtest PF, `pf_vs_backtest %`). Backend rule: validated ≠ sized; Kelly sizing requires ≥20 closed forward trades AND forward PF > 1 (`forward_test.py::graduation_readiness`), promotion is a deliberate manual step.
- **Jarvis state:** the concept half-exists — `/scorecard` has promotion gates (PF≥2.0, WR≥50%, DD<8%, 60+ days) and the engine has `GET /forward-test/status` and `GET /analytics/forward-test`, but **`ForwardTestPanel.tsx` is built and unmounted**, so forward-test graduation is invisible.
- **Proposal:** first mount the orphaned `ForwardTestPanel` (near-zero cost); then add an amo-style side-by-side forward-vs-backtest PF comparison to `/scorecard` fed by `/forward-test/status`. The paper→live gate itself already exists in jarvis governance — this is purely making it visible.
- **Effort:** S (mount) + M (scoreboard). **Value: high**, directly serves the Phase-2→Phase-3 decision.

### Tier 3 — UX kit (small, compounding wins)

#### P7. Unified system-health hook
Amo's `useSystemHealth.ts`: **one** 60s poll of one status endpoint, React-Query-deduped, consumed by the header badge, sidebar dot, dashboard strip, ops page, and every `FreshnessStamp` — four surfaces that *cannot disagree*. Jarvis polls `/health` from multiple components independently (audit showed exactly the drift/hammering this prevents, incl. during engine outages). Port as an SWR hook wrapping `/health/full`. **S, medium-high value.**

#### P8. Per-page `FreshnessStamp` + freshness registry concept
Amo stamps every data page "X as of Jul 1, 5:00 PM CT ⚠" from a single backend `freshness.REGISTRY` (per-table SLA, weekend-aware, CI test asserts every scheduled producer is enrolled). Jarvis has per-value envelopes (`as_of`, `stale_after_s`) but no per-page stamp and no engine-side SLA registry with a CI enrollment audit. The registry-with-CI-test idea is the deeper win (catches the "pipeline connected, ran, wrote nothing" class — amo's `expect_rows`/`stale_success` detection). **S (stamp) / M (registry), medium-high value.**

#### P9. Command palette page-navigation with keyword aliases
Jarvis's Cmd+K is ask-only (`POST /jarvis/ask`). Amo's palette also fuzzy-jumps to pages with domain aliases ("ruin"→Monte Carlo, "kelly"→Targets), generated from the nav source of truth. With 44 routes, jarvis needs this more than amo does. Extend the existing `CommandPalette.tsx` — keep ask as the fallback action. **S, medium value, high polish.**

#### P10. Drop-in CSV export
Amo's `ExportCsvButton.tsx` is a generic per-table download. Jarvis has exactly two global CSV exports (trades, daily P&L). Add the drop-in to trades, journal, scorecard, and any new outcomes table. **S, low-medium value.**

#### P11. `InfoHint` micro-tooltips
Amo puts a ⓘ hint on every jargon metric (P(Ruin), IC gate, MFE/MAE, IV rank). Cheap self-documentation for jarvis's WFE / Brier / debate-score / gate-v2 vocabulary. **S, low-medium value.**

#### P12. Public-style status page with uptime timeline
Amo persists reconciled health snapshots (`system_snapshot.py`) and renders a 240-cell uptime timeline + `uptime_pct`. Jarvis's `/health` shows *now* but has no uptime history — and the 2026-07-10 audit's core finding (engine crashed twice, unnoticed) is precisely what this surfaces. Engine: persist a snapshot per health poll; dashboard: timeline on `/health`. **M, medium value, high ops payoff.**

### Tier 4 — Analytics & engine-side (deeper, optional)

#### P13. Monte Carlo fan chart + scenario rescale + ruin tiles
Jarvis `/validation` shows MC confidence intervals as a card; amo shows a **percentile fan chart** (p5/p25/p50/p75/p95 equity curves, `LightweightFanChart.tsx` — jarvis already ships lightweight-charts 5.1, so it drops in), a block-bootstrap drawdown histogram, tiles for `p_ruin`/`p_target`/VaR/CVaR, and a `ScenarioExplorer` that rescales stored percentiles **exactly, server-side** (never re-simulates, refuses to fabricate path-level stats). Engine work: emit per-step percentile curves from the existing MC analytics. **M–L, medium value.**

#### P14. Five-pillar convergence grid, applied to jarvis's own analysts
Amo's morning brief renders a per-symbol grid of pillar votes (▲▼–) with a −5..+5 total and convergence score. Jarvis's S1 analysts (TECH/NEWS/SOCIAL/MACRO) + regime are the same shape; a per-symbol analyst-vote strip on the pipeline/command-center views would make the debate's *inputs* glanceable the way `LiveTradeReasoningWidget` makes its *narrative* readable. Display-only over data the pipeline already records. **M, medium value.**

#### P15. Regime-at-entry attribution on trade outcomes
Amo tags every outcome with `regime_at_entry` and aggregates hit-rate per regime. Jarvis has `RegimeAttributionWidget` (performance) — extend the honest trade record / journal with regime-at-entry so the same "edge or regime?" question is answerable per-trade. **M, medium value.** Point-in-time rule applies (label from data available at entry time only).

#### P16. Pre-registration hardening (engine/process, not UI)
Jarvis already has `family_fdr.py` (ported from amo). What it does *not* have: amo's **frozen, tamper-hashed hypothesis family** (`preregistration/family.py`: sha256 freeze over date|family|q|sig, absent members padded p=1.0 so m never shrinks), the **frozen OOS holdout with `assert_no_holdout_leak`**, and the **additive trial ledger** (`hypothesis_trials`, never deleted, returns `None` not `0` when degraded — so "no prior trials" can't be faked by a missing migration). All three are small pure modules that directly serve the no-look-ahead testing rules. **M, high value for research integrity, zero UI.**

### Explicitly NOT proposed
- Any path where amo signals gate/veto/size a jarvis trade (violates CROSS_SIGNAL spec).
- Amo's Kelly sizing math driving jarvis position sizes (jarvis sizing bounds live in safety-reviewed code; amo's *withhold-sizing-until-validated* **pattern** appears above as P6, the numbers do not cross systems).
- 3D surface pages (jarvis already has an unmounted three.js HUD subsystem; 3D is polish, not edge).
- A second LLM research-chat page (jarvis's Cmd+K ask already covers it).

---

## 4. Sequencing recommendation

1. **Week 1 (all S, mostly mounting existing work):** P4 ResultLabel → P6a mount `ForwardTestPanel` + mount `ConfidenceGauge` → P3 deepen amo advisory display → P9 palette nav → P7 health hook.
2. **Week 2 (the predictions core):** P1 signal-outcome scoreboard (dashboard first over `/analytics/signal-quality`, then the engine evaluator) → P2 actionable board.
3. **Week 3+:** P5, P8 registry, P12 uptime, P6b scoreboard, then Tier 4 by appetite.

A useful forcing function: jarvis has ~15 built-but-unmounted components (`ForwardTestPanel`, `ConfidenceGauge`, `AgentWeightsPanel`, `RollingWFEWidget`, `ShadowPerformanceWidget`, the entire `components/command-center/` HUD…). Several Tier 1–2 items are "mount + restyle" rather than new builds — check the orphan list before writing anything new.

---

*Analysis: static source read of both repos on 2026-07-16. No runtime behavior verified; no code changed by this document.*
