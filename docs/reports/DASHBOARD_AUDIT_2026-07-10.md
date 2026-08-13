# Jarvis-Trader Dashboard — Exhaustive Playwright Audit

**Date:** 2026-07-10
**Method:** Direct Playwright automation (headless Chromium, sequential single-session sweep) against the live dashboard at `http://localhost:3010`, driven by this Claude Code session — not a self-report, not a prior-session recollection. All 41 top-level routes tested. Raw results: `C:\Users\mattm\.claude\jobs\c668d768\tmp\dashboard-audit-results.json`. Screenshots: `C:\Users\mattm\.claude\jobs\c668d768\tmp\shot-*.png`.
**Why this file exists:** No prior dashboard-integrity audit file could be found anywhere on disk. Two loops (`dashboard-integrity-audit-cadence`, `jarvis-audit-fix-drain`) were registered 2026-07-09 to maintain one, but both show `last_heartbeat: null` — they never fired. This is the first real audit artifact for this dashboard.

---

## 0. Critical, load-bearing context — read this before the findings

**The engine crashed twice during this audit window**, and that materially colors how to read the results below.

1. Engine was found down (`connection refused`) at audit start. Root cause: a **transient port-bind collision** on 8010 (`[Errno 10048]`) at 2026-07-09 23:53:30, from which the engine did not cleanly recover.
2. Restarted via `restart_engine.ps1` (Amo-authorized, resource-locked). Came up healthy: `status:ok`, IB Gateway connected, database connected. Verified independently, twice.
3. **~4 minutes into the 41-page sweep, the engine crashed again** — confirmed by `netstat` showing a new PID on :8010 with `CLOSE_WAIT` connections piling up, and `/health` going unresponsive. `master-api` (:8030) went unreachable at the same time.
4. Host RAM was measured at **96–97.5% used, 0.8–1.25GB free** throughout this session, with 900–1050+ total processes (from ~7-8 concurrent Claude Code sessions and their spawned tooling). This is the most likely root cause of both crashes — not a dashboard-code or engine-code defect.

**Implication:** findings that manifest as "engine unreachable / 502" are downstream of host-level resource exhaustion, confirmed live and ongoing, not necessarily independent dashboard bugs. They are listed below with that caveat. A clean re-audit is needed once the host RAM crisis is resolved to know which of these are *also* independent bugs versus purely collateral damage.

---

## 1. Severity tiers

- **Tier 1 — Structural / blocks core function.** Missing routes, hydration-crashing pages, or pages that hang instead of degrading.
- **Tier 2 — Functional but engine-dependent.** Pages that render correctly and fail honestly when the engine is down; real bug only if it recurs against a *stable* engine.
- **Tier 3 — Cosmetic / minor.** Nav duplication, etc.

---

## 2. Tier 1 findings (structural — independent of engine state)

### 2.1 — `/mission-control` returns HTTP 404
Full nav renders; the route itself does not exist. Screenshot confirms a deliberate, well-styled 404 page ("ROUTE NOT FOUND — this endpoint does not exist in the trading system"), not a crash.
**Root cause (corroborated):** PR **#292** *"feat(dashboard): MISSION CONTROL command-center page + local fleet API route"* is still open/draft, `mergeable=UNKNOWN`. The page was built but never merged/deployed.
**Fix:** merge #292 (Amo-gated — review first, it's draft for a reason).

### 2.2 — `/framing-brief` returns HTTP 404
Route exists in the file tree (`app/framing-brief/page.tsx`) but 404s live. Single console error (`Failed to load resource: 404`), single network failure.
**Hypothesis (unverified):** either the page has a nested/dynamic segment not covered by the bare path, or a server-side data dependency throws before Next.js can render it, and Next surfaces that as a 404 rather than an error boundary. Needs a source read of `app/framing-brief/page.tsx` to confirm — not done here (would require code inspection beyond this audit's browser-only scope).

### 2.3 — `/` (root) and `/trades` hang for 15s+ and never load
Both timed out on `domcontentloaded` (Playwright's 15s ceiling), producing **zero page content** — not even a shell. This is qualitatively worse than every other engine-dependent page, which rendered their shell and reported per-widget errors honestly (see 2.4 pattern below).
**Hypothesis, moderately confident:** `/` and `/trades` perform a **blocking server-side data fetch** against the engine before sending any HTML (likely SSR or a server component awaiting engine data), with no timeout/fallback. Every other route appears to fetch client-side after the shell renders, so an engine outage degrades them gracefully instead of hanging the whole page. If confirmed, this is a real architectural defect independent of the engine's live/down state — a slow engine (not just a dead one) would produce the same hang.
**Action needed:** re-test both against a *stable* engine to separate "confirmed architectural hang" from "was purely a symptom of the engine being down at that exact second." If it reproduces even with the engine healthy and merely slow, fix by moving the data fetch client-side or adding a hard SSR timeout with fallback UI, matching the pattern already used elsewhere in this app.
**Severity note:** `/trades` is the trade-history/ledger page — Tier 1 by content (P&L-adjacent), and doubly so by this failure mode (total hang, not honest degradation).

### 2.4 — `/performance` and `/stats`: React hydration error #418
Both throw `Minified React error #418` (server/client render mismatch) as an uncaught `pageerror`, not a console warning. Page still returns HTTP 200 and no network failures, so it's rendering *something*, but with a real hydration bug underneath.
**Fix path:** re-run against a dev (non-minified) build to get the actual error text — the minified build only gives a lookup code. This is a genuine, engine-independent front-end bug.

### 2.5 — Duplicate "Hidden Pivots" nav entry (Tier 3, bundled here for completeness)
The sidebar lists **"Hidden Pivots" twice** — once under the general trading nav, once under "Analysis." Confirmed visually on the `/mission-control` 404 screenshot (nav renders identically across pages). Cosmetic, not a functional defect, but worth a one-line fix.

---

## 3. Tier 2 findings — engine-dependent pages (degraded honestly, root cause = engine outage)

These five pages returned HTTP 200 with a correctly-rendered shell, and **every failed widget explicitly reported the real cause** ("Engine error 502", "engine restart pending", "Engine offline or honest trade record unreachable") rather than showing blank/fake/stale data. This is good, safety-conscious error handling — consistent with the project's own "never overstate readiness" principle — and should not be read as a dashboard defect on its own:

| Route | Console errors | Network failures (502s) | Notes |
|---|---|---|---|
| `/validation` | 27 | 26 | Worst-hit. Full breakdown in §3.1. |
| `/watchlist` | 14 | 13 | |
| `/trust-pane` | 8 | 7 | |
| `/master` | 1 | 1 | Single call: `/api/master/master/status` |
| `/research-log` | 1 | 1 | Single call: `/api/master/master/trading/realized` |

All five also show a WebSocket connection failure to `ws://127.0.0.1:8010/ws/events` (`ERR_CONNECTION_REFUSED`) where applicable — consistent with the engine being down at test time, not a separate bug.

### 3.1 — `/validation` in detail (worst-affected page, screenshot-verified)
Full page renders. Per-widget breakdown from the actual screenshot:
- **GO/NO-GO Validation Checklist** — 0/6 criteria met, all rows "No data / PENDING" (correct behavior with no engine).
- **Instrument Approval Scorecard** — **renders real data** (MCL WFE=0.82 APPROVED, MNQ WFE=0.57 APPROVED, MES WFE=0.09 Revalidating). This table is NOT engine-dependent — likely reads a cached/static baseline. Works correctly.
- **MES Revalidation**, **MES Forward-Recorder** — explicit `Engine error 502` on their specific endpoints.
- **Monte Carlo Confidence Intervals**, **Parameter Sensitivity Analysis**, **Statistical Significance** — all explicitly say "unreachable — engine restart pending to display live validation analytics."
- **Backtest Reference (saved engine JSON)** — **renders real data** (MCL/MNQ baseline, STC(55,15,65)+ATR Stop 0.75x strategy spec). Static, works correctly.
- **Trading Phase Status roadmap** — static UI, renders correctly (Phase 1 Backtest complete, Phase 2 Paper Trading in-progress, Phase 3 Live locked).
- **Simulate Trade** form — a live order-simulation form with a submit button. **Present but NOT exercised** — out of scope for read-only audit, and correctly so (this audit never submitted any form or clicked any mutating control, per the trading-safety constraint).
- **Pipeline Run History** — "Failed to load pipeline history — engine may be offline."
- **Position Sizing Calculator** — renders correctly (appears client-side, no engine dependency).
- **Position Reconciliation** — "Reconciliation data unavailable — Engine error 502."
- **Go-Live Roadmap** — static, renders correctly ($10,000 paper / $10,000–25,000 live account tiers shown).
- **WFE Monitor**, **Portfolio Cumulative P&L** — both engine-502'd.

**Verdict on `/validation`:** the page's error handling is sound. Its actual defect right now is 100% "the engine is down," which is the P0 finding of this entire audit, not a `/validation`-specific bug.

---

## 4. Clean pages (34 of 41 — no errors, no anomalies)

`/analysis`, `/atr-trail`, `/backtest`, `/command-center`, `/config`, `/crypto`, `/data-integrity`, `/discord`, `/health`, `/hidden-pivots`, `/jarvis`, `/journal`, `/journal-review`, `/kairos`, `/learning`, `/options`, `/paper`, `/parallel-paper`, `/polymarket`, `/portfolio`, `/regime`, `/scorecard`, `/screener`, `/settings`, `/strategies`, `/strategy-c`, `/strategy-c-command`, `/strategy-ledger`, `/strategy-research`, `/today`

All loaded HTTP 200, zero console errors, zero network failures, zero text anomalies. Note: several of these (portfolio, backtest, paper) are exactly the pages you'd expect to hit the engine hardest — their clean run happened to fall in the first ~4 minutes before the second crash. **These need re-verification too**, not just the ones that failed — a clean result during a narrow healthy window isn't the same as a durable clean result.

---

## 5. The one finding that supersedes all of the above

**The host this dashboard and engine run on cannot currently sustain a stable engine process.** Two crashes in roughly 10 minutes, both correlated with 96–97.5% system RAM usage from a large number of concurrent Claude Code sessions and their spawned processes. Every Tier 2 finding in this document is downstream of that fact. Fixing dashboard code, merging PR #292, or restarting the engine again will not produce a durable fix until that's addressed — the next restart will likely also fail within minutes under the same conditions.

---

## 6. Recommended next steps, in order

1. **Resolve host RAM pressure** (Amo-gated — this is the session/process wind-down question from earlier in this session). Without this, nothing below is durable.
2. **Re-run this exact audit** once the engine has been stable for 15+ minutes, to get a clean read that separates confirmed bugs from engine-outage collateral. The script is saved and reusable: `C:\Users\mattm\.claude\jobs\c668d768\tmp\dashboard-audit.js`.
3. **Fix Tier 1 items independent of engine state:** merge #292 (mission-control), investigate `/framing-brief` 404 (needs a source read), reproduce and fix the `/performance` + `/stats` hydration error #418, dedupe the "Hidden Pivots" nav entry.
4. **Specifically re-test `/` and `/trades`** against a stable-but-artificially-slowed engine to confirm or rule out the blocking-SSR-hang hypothesis — this is the single most safety-relevant Tier 1 item (a P&L/ledger page that hangs entirely rather than degrading).
5. Consider seeding `backlog.json` for the two dormant loops (`dashboard-integrity-audit-cadence`, `jarvis-audit-fix-drain`) from this report so they can actually start doing their intended job going forward — not done in this pass, flagged as a fast follow.

---

## 7. What was explicitly NOT done (scope discipline)

- No form was submitted, no button that mutates state was clicked (Simulate Trade, kill-switch controls, settings saves, etc.) — read-only navigation and observation only, per trading-system safety norms.
- No source-code changes were made to the dashboard or engine as part of this audit.
- No strategy math, backtest logic, or position-sizing code was touched or evaluated for correctness — this audit is UI/integration-layer only.
