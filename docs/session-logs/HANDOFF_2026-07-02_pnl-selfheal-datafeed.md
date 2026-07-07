# HANDOFF — 2026-07-02 — P&L double-count fix, daily_pnl self-heal, data-feed blindness

**Session:** `session_01Ebutnyr4dQCFdatQ51wUNd` (continuation of uuid `b2ebcf3b-f06c-4765-b2ab-6fa1767d0291`)
**Branch:** `fix/corey-standalone-vertex-routing`
**Author:** Claude Opus 4.8 (1M context) with Amo (Matt Amundson)
**Scope:** JARVIS TRADER paper-P&L accounting integrity + engine/data-feed state

> **North star (verbatim framing):** paper-account signals drive REAL-money trades. Amo wants
> *real edge, not green checks*; liveness confirmable at a glance; and **brutal honesty** — trust is
> the asset, over-stating readiness costs real money.

---

## 1. Current state (what's running / broken / verified)

| Thing | State | Evidence |
|---|---|---|
| Engine (pm2 `jarvis-engine`) | **online**, restarted this session on the fixed code+config | `/health status=ok tv=True llm=True` |
| `portfolio_equity` | **$15,081.84** (was inflated $20,163.67) | `/safety/status` post-restart |
| Daily-loss limit | **8% PCT + $1,000 USD flat** (was 6% / $100) | `/safety/status daily_limit_pct=-0.08` |
| Kill-switch | **inactive** (cleared this session) | `/health kill_switch_active=False` |
| **IB data feed** | **🔴 BLIND** — see §4 | `ibkr_data_connected=False`, prices `source=csv_cache` |
| daily_pnl table | rebuilt clean ($15,081.84 final ending, 0 identity violations) | Fix B applied |
| daily_pnl self-heal | **shipped + committed** (`e02ec8d`), auto-runs post-EOD | 83/83 tests green |

**Paper only.** `LIVE_TRADING_ENABLED=False`. Live IB port 4001 permanently blocked. Paper port 4002.

---

## 2. The P&L double-count saga (root cause → fixes A/B/C)

**Symptom:** `/safety/status` reported `portfolio_equity=$20,163.67` while `/portfolio/history/daily-pnl`
ended at $14,712.84. Ground truth (closed `paper_trades` ledger): **$10,000 initial + $5,081.84 net
closed P&L = $15,081.84 TRUE equity.**

**Root cause (double-count):** `portfolio/tracker.py::_get_starting_balance()` returned
`INITIAL_CAPITAL + SUM(closed pnl)` — already the true equity, but MISNAMED as a "starting" base. Both
consumers (`risk/pnl_monitor._read_memory`, `tracker.get_performance_summary`) then add `total_pnl`
*again* → `initial + 2×total_pnl`. Verified to the penny: `$10,000 + 2×$5,081.8365 = $20,163.673`.

> ⚠️ **Correction recorded for honesty:** I first told Amo the tracker ($20,163) was accurate and the
> daily_pnl table was corrupt. **That was BACKWARDS** — the tracker double-counts. Corrected mid-session
> with penny-exact proof. The lifetime number (`/portfolio/stats/summary total_pnl=+$5,081.84`) was the
> only reliably-correct figure.

### Fix A — the double-count (`b74fe25`, committed by a peer session, pushed)
`_get_starting_balance()` now returns `INITIAL_CAPITAL` (pnl-FREE). Consumers add `total_pnl` once →
equity counted once. **Tradeoff:** `daily_pnl_pct` denominator reverts to initial capital
(reporting-only; the daily-loss gate reads `portfolio_equity`, now correct). Regression test
`tests/test_pnl_equity_no_double_count.py` (fails before, passes after).
**Note:** the prior-session Fix A was *lost* before commit — a peer's `tracker.py` refactor (`1a81ea4`)
+ a `pre-master-merge` stash discarded the uncommitted edit. Re-derived against refactored code and
committed immediately. **Lesson: with live peers, never leave a fix uncommitted.**

### Fix B — daily_pnl history rebuild (one-time, applied)
`engine/scripts/repair_daily_pnl.py` (committed `4f89ac2`) replayed closed trades from $10k. DB backed
up to `~/Archive/2026/jarvis-db-backups/jarvis_trader_pre_dailypnl_rebuild_20260702.db` (296 MB).
Applied: DELETE 19 corrupt rows → INSERT 15 correct rows. realized SUM +$5,081.84 == ledger; final
ending $15,081.84; **07-01 row now +$102.75 (was phantom −$266.25)**; zero identity violations; 4 orphan
dates removed.

### Fix C — INVESTIGATED, no code change needed
The pre-compaction "Fix C gap" was diagnosing **dead code**. `risk/pnl_monitor.record_eod_snapshot` (the
writer feared to trip the guard) has **zero production callers** — only tests reference it. The **live**
EOD writer is `schedulers/eod_scheduler.EODScheduler.run_eod_snapshot` (registered `main.py:1610`), which
**absolute-anchors** balances to `initial_capital + cumulative status='closed' P&L`
(`_collect_db_trade_metrics`, the 2026-06-12 fix). It satisfies `ending==starting+realized` by
construction, excludes phantom/cancelled, and does not chain off prior rows. No fix required.

**Live effect:** engine restarted (jarvis-engine resource lock claimed→released, PM2 path). Verified
`portfolio_equity=15081.8365`, health ok/tv/llm, kill-switch clear. Number correct everywhere — code, DB,
running process.

---

## 3. The daily_pnl self-heal (NEW this session — `e02ec8d`, unpushed until §7)

**Why:** the EOD row counts whatever is `status='closed'` at the 20:05 UTC snapshot. Phantom/duplicate
trades are marked `status='phantom'` **manually** (`scripts/mark_phantom_trades.py`, a hardcoded ID list)
*days later* — so a stale row survives. `reconcile_daily_pnl` (2026-06-15) **detected** drift but nothing
**repaired** it. The 07-01 phantom −$266 that latched the kill-switch is the motivating case.

**What shipped:**
- **`DailyPnLMixin.repair_daily_pnl`** (`engine/database/_mixins_pnl.py`) — corrective sibling to the
  detective `reconcile_daily_pnl`. Rebuilds the table from the closed ledger using the SAME
  absolute-anchoring formula the EOD writer uses. Every rebuilt row satisfies the identity by
  construction; excludes phantom/cancelled; idempotent; `dry_run=True` default.
- **Wired into `run_eod_snapshot`** (`engine/schedulers/eod_scheduler.py`) — after persisting today's
  row, it reconciles and, on drift, repairs. The table self-corrects the cycle after a phantom is marked.
- **Safety:** DB-only, reversible (rows are a pure derivation), guarded so a heal failure never blocks
  EOD, and it **does NOT touch the kill-switch** (that halt-logic change is a separate safety-critical
  decision left to Amo).
- **Tests:** `tests/test_daily_pnl_self_heal.py` (5) — dry-run no-op, rebuild+reconcile-clean, phantom
  exclusion, idempotency, end-to-end EOD wiring on a real DB. **83 pass** across daily_pnl/eod/pnl suites.

**Known behavior:** a heal zeroes the reporting-only `max_drawdown`/`unrealized_pnl` columns on rebuilt
rows (per-day intraday DD isn't reconstructable from EOD closed rows). Nothing load-bearing reads them
(the kill-switch uses `portfolio_equity`, not `daily_pnl.max_drawdown`). A legitimate zero-trade day's row
is treated as an orphan and removed on heal (the table is a pure derivation of the closed ledger).

---

## 4. 🔴 BLOCKER — the IB data feed is BLIND (highest-ROI open item)

Discovered while verifying real-time data:
- `/prices/snapshot` returns `source: "csv_cache"` — **stale cached CSVs, not live market data.**
- `/health`: `ibkr_data_connected=False`, `ibgateway_alive=False` (port 4002), while top-level
  `ibkr_connected=True` (the misleading short-circuit — true from the *execution* side only).
- `.env` line 74 `IB_ACCOUNT_ID=DUP662235` — still the **old** paper account, never swapped to the
  real-time-subscribed `DUR162217`.

**Impact:** every signal the engine produces right now is on stale prices. This undercuts the north star
at the source — MES edge validation, the STC trigger loop, any paper→real thesis are all compromised
until the feed is live. **This dominates the P&L reporting work in priority.**

**Matches the 07-02 memory incident** (`feedback_ib_probe_no_background_2026_07_02`): a backgrounded
`ib_probe.py` + unclean kill wedged the Gateway data API. **Rule honored: I did NOT run an IB probe**
(probing/killing one is what wedges it further).

**Fix (two steps, in order):**
1. **Amo relogs the IB Gateway GUI** (data API is wedged — GUI action, Amo-only).
2. Then Claude edits `.env` line 74 `DUP662235 → DUR162217`, claims the `jarvis-engine` resource lock,
   restarts, and verifies `/prices/snapshot` shows a live source (not `csv_cache`) +
   `ibkr_data_connected=True`.

---

## 5. Other decisions made this session

- **Daily-loss limit raised to 8% + $1,000 USD** (`engine/.env`: `MAX_DAILY_LOSS_PCT=0.08`,
  `MAX_DAILY_LOSS_USD=1000`). Non-obvious: the halt is TWO gates in `risk/safety_layer._check_daily_loss_limit`
  (PCT on total P&L + USD flat on realized), both latch as `daily_loss_limit`. The old **$100 flat** is
  what latched on 07-01 (−$266 realized), NOT the 6% PCT gate — so changing only PCT would have been
  cosmetic. Both moved together. `.env` changes are the secret store — **intentionally NOT committed.**
- **Kill-switch latch cleared** via `POST /safety/kill-switch/deactivate` (was halting all paper trades on
  the phantom −$266).
- **Status-push loop** (`jarvis-status-push`, prior in session): its "profitable?" line computes true
  equity = `$10k + stats/summary total_pnl`, NOT the (then double-counted) tracker equity.
- **MES sizing finding** (prior in session): CORE gate v2 flips PASS at **~$16,750/contract**; comfortable
  at $20–25k ($20k→5.09% MC DD, $25k→4.13%). Honesty caveats: n_trades=36 (thin), still paper, delayed
  feed, sizing ≠ edge. **Not promoted** — needs walk-forward before any live sizing call.

## 6. Billing (finding, Amo-gated)

CC 07-01 burn: **$850.16/day** (Opus 4.8 = ~84%). BUT `~/.claude.json` shows `oauthAccount` → CC is on
**subscription auth, not metered API billing**, so that $850 is almost certainly **rate-card-notional
against a plan, not out-of-pocket.** **Action:** Amo runs `! /status` — if Max 20×, it's a usage meter,
no action. Real lever regardless of plan: 84% on Opus; routing non-critical work to Sonnet 5 stretches
limits.

---

## 7. Git state

**Branch:** `fix/corey-standalone-vertex-routing` (89 ahead / 236 behind `master`; also carries the
superseded always-on Gemini routing — the P&L fixes are cleanly isolated in the commits below).

```
e02ec8d feat(pnl): self-heal daily_pnl drift after phantom reclassification   [THIS + handoff = unpushed at write time]
4f89ac2 fix(portfolio): stop double-counting P&L in equity calc               [engine/scripts/repair_daily_pnl.py]
b74fe25 fix(portfolio): count paper equity once — pnl-free starting balance   [tracker.py + test, peer-committed]
```

**Files changed this session (committed):**
- `engine/portfolio/tracker.py` — `_get_starting_balance` returns pnl-free base (Fix A, `b74fe25`)
- `engine/tests/test_pnl_equity_no_double_count.py` — Fix A regression (`b74fe25`)
- `engine/scripts/repair_daily_pnl.py` — one-time + re-runnable ledger rebuild (`4f89ac2`)
- `engine/database/_mixins_pnl.py` — `repair_daily_pnl` corrective method (`e02ec8d`)
- `engine/schedulers/eod_scheduler.py` — post-EOD self-heal wiring (`e02ec8d`)
- `engine/tests/test_daily_pnl_self_heal.py` — 5 self-heal tests (`e02ec8d`)

**NOT committed (intentional):** `engine/.env` (secret store) — holds the 8%/$1000 daily-loss config.

---

## 8. TODO / next actions (priority order)

1. **🔴 Relog IB Gateway (Amo) → then Claude swaps `.env` to `DUR162217` + restart + verify live feed.**
   Highest ROI — unblocks signal quality. §4.
2. **`! /status`** — settle the billing question (likely already capped on Max). §6.
3. **Phantom detection is manual** — the self-heal fixes *reporting* drift, but a phantom still latches
   the kill-switch in the live realized stream until marked. A durable fix = automated duplicate/phantom
   detection BEFORE the EOD snapshot, or a kill-switch design that doesn't halt on a single-trade outlier
   (safety-critical — Amo's design call, explicitly NOT touched here).
4. **Optional:** expose `repair_daily_pnl` as an on-demand corrective endpoint on `analytics_router` so a
   heal can be triggered right after `mark_phantom_trades.py` without waiting for EOD.
5. **MES sizing** — walk-forward validation before any live sizing decision. §5.
6. **Push discipline** — the P&L fixes live on a divergent feature branch. If wanted on `master` without
   the Gemini-routing baggage: cherry-pick `b74fe25` + `4f89ac2` + `e02ec8d` onto a fresh branch off
   `master`. Amo's call.

## 9. Suggested next action (ONE thing)

**Relog the IB Gateway GUI, then tell Claude "feed is up."** Everything else is secondary until the engine
is trading on live prices instead of `csv_cache`.
