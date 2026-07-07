# US-009 — Strategy C+ Command Center Reconcile

**Date:** 2026-06-12  
**Branch:** ralph/edge-24x7  
**Verdict:** ZIP IS SUPERSEDED — live dashboard is the canonical, more-evolved version.  
**Code changes:** NONE.

---

## 1. Zip Contents

The zip (`JARVIS Strategy C+ Command Center (3).zip`) contained exactly two files:

| File | Size | Modified |
|---|---|---|
| `index.html` | 344,549 bytes (9,585 lines) | 2026-06-02 |
| `index.html.bak` | 332,700 bytes (9,258 lines) | 2026-06-02 |

The `.bak` is an older snapshot of the same file (327 fewer lines, 389 diff lines vs the current `index.html`). Both are standalone HTML files meant to be opened from disk as a self-contained dashboard.

---

## 2. Live Implementation

The live Strategy C+ Command Center is served at `http://127.0.0.1:3010/strategy-c-command` via two components:

- **`dashboard/app/strategy-c-command/page.tsx`** — a minimal Next.js page (25 lines) that renders a full-bleed `<iframe>` pointing to `/strategy-c-command-center.html`.
- **`dashboard/public/strategy-c-command-center.html`** — 344,549 bytes (same size class as the zip), modified 2026-06-11.

There is also a separate **`dashboard/app/strategy-c/page.tsx`** (683 lines of React/TypeScript) that provides a structured TSX-based view of the Strategy C+ live signal and backtest metrics, pulling from `GET /v1/strategy_c/signal` and `GET /v1/strategy_c/metrics`.

---

## 3. Diff Verdict

SHA256 hashes confirm the zip `index.html` and the live `strategy-c-command-center.html` are **not identical** despite having the same byte count (344,549). A full line-by-line diff produced exactly **11 changed lines** — all of the same class:

| Change | Count |
|---|---|
| `http://localhost:8020` → `http://127.0.0.1:8020` | 10 occurrences |
| `allowedParentOrigins` array: `http://localhost:3000` → `http://127.0.0.1:3000` and `http://localhost:5173` → `http://127.0.0.1:5173` | 1 line |

**This is the Windows IPv6 fix** documented in `rules/windows-pitfalls.md`: on Windows 11, `localhost` resolves to `::1` (IPv6) before `127.0.0.1`, so any service binding IPv4-only silently fails. The live version applies this fix across all 10 API endpoint references to the 8020 bridge.

The zip (`index.html`, dated 2026-06-02) is the **pre-fix prototype** exported from a browser session before the Windows IPv6 localhost correction was applied. The live file (modified 2026-06-11) is the zip + the 11-line fix integrated during the 2026-06-11 audit closeout session.

**Conclusion: the zip is an archival snapshot. The live file supersedes it in every respect.**

---

## 4. What the Command Center Monitors

The Strategy C+ Command Center is a single-page, real-time operations dashboard for the JARVIS Strategy C+ weekly-rebalance ETF momentum strategy. It displays: a scrolling ticker bar with live futures prices (ES, NQ, MNQ, MCL); a radial-arc combined-scale gauge and regime badge (RISK_ON / RISK_OFF); a current holdings grid with per-symbol weights; a Cohen v3 EMA trend panel for MES/MNQ/MCL; macro indicators (10Y yield, yield-curve spread, VIX level + momentum, BTC, Gold); a live gainers/losers board; a system activity log feed; and a multi-tab charting section (equity curve, weekly drawdown, drawdown wick chart, rolling Sharpe) rendered via Chart.js. All dynamic data is fetched from `http://127.0.0.1:8020` (the IBKR/options/regime bridge) and `http://127.0.0.1:8010` (the JARVIS engine API). The dashboard auto-refreshes on a 30-second countdown visible in the header.

---

## 5. Reconcile Actions

| Action | Result |
|---|---|
| Unpack zip and inspect | Done — 2 files, both are the same HTML artifact |
| Diff zip vs live | 11 lines: all `localhost` → `127.0.0.1` (Windows IPv6 fix) |
| Determine superseded vs has-new-features | **Superseded** — live is strictly superior (has the IPv6 fix) |
| Port any features from zip | Not applicable — live already contains all zip content |
| Code changes | None |
| Typecheck | Not required (no .tsx changes) |

---

## 6. Files to Commit

| File | Action |
|---|---|
| `scripts/ralph/STRATEGY_C_RECONCILE.md` | New — this document |

No dashboard source files were modified.
