# JARVIS Trader — Trade System Scope & Forward Roadmap

_Authored 2026-06-01. Maps the full execution → journal → validation chain, flags a
two-ledger integrity gap, and scopes two proposals: (A) decoupling edge-proof from
execution-fidelity in the validation gate, and (B) a multi-entry trend WFO to lift
trade frequency. Proposals are NOT implemented — validation/readiness code is
safety-adjacent and requires explicit [safety-review] approval before any change._

---

## Part 1 — Execution & Brokerage (where orders actually go)

### Brokers

| Broker | Status | Account / Port | Scope | File |
|---|---|---|---|---|
| **Interactive Brokers** | **ACTIVE (paper only)** | `DUP662235` / port **4002** | Futures (MES/MGC/MNQ/MCL…) | `engine/execution/ib_gateway.py` |
| Schwab | Scaffolded, dormant | OAuth, `SCHWAB_READY=False` | Equities + options | `engine/execution/schwab_connector.py` |
| Polymarket | Experimental | CLOB, dormant | Prediction markets | `engine/execution/polymarket_connector.py` |
| Kraken/Freqtrade | Dormant | — | Spot crypto | `engine/markets/crypto/` |

### Live-trading safety gates (all confirmed ON)

- `LIVE_TRADING_ENABLED = False` — `config.py:288`
- `REQUIRE_HUMAN_APPROVAL = True` — `config.py:289`
- Live ports **4001 / 7496 hardcoded-rejected** — `ib_gateway.py:196-237` (raises `ValueError`)
- Bracket orders hard-assert `LIVE_TRADING_ENABLED=False` — `brokers/bracket_orders.py:291`
- Kill switch (−2% daily / −10% drawdown) — `risk/safety_layer.py:87`, human-only reset

### Two distinct order paths

1. **Standalone paper_runner** (`engine/backtest/paper_runner.py`)
   → generates SMA signals → records to SQLite `paper_trades` (`account_id='A'`)
   → **never contacts a broker.** Pure internal simulation with Polygon/engine bar prices.
   **This is the strategy-validation harness.**

2. **Full engine pipeline** (agents → approval → `order_router` → `ib_gateway`)
   → can route real orders to the IB **paper** account on port 4002.
   → real executions land in SQLite `ibkr_fills`.

---

## Part 2 — ⚠️ The Two-Ledger Integrity Gap (critical)

The system keeps **two trade ledgers that do not reconcile:**

| | `paper_trades` | `ibkr_fills` |
|---|---|---|
| Source | paper_runner simulation | Real IB paper account |
| Account | `'A'` (internal label) | `DUP662235` (real IB) |
| Rows (2026-06-01) | 5 closed | 4 fills (all BOT, no sells) |
| Read by journal-review? | **YES** | no |
| Counted by validation gate? | **YES** | no |
| Prices realistic? | yes | **no** — MES @7611, MNQ @30490 vs real ~6000 / ~21000 |

**Implications:**
- The journal and the validation gate measure **only the simulation.** Real orders that
  hit the IB paper account are invisible to both.
- The 4 `ibkr_fills` (imported in one batch at 09:16:38 UTC) have prices far above real
  contract levels — consistent with the pre-seeded **"Individual Demo"** portfolio noise
  documented in `project_paper_account_40pct_demo_seed_2026_05_31.md`, **not** JARVIS-placed
  trades. But they are genuine fills on the real IB paper account, with real CME exec_ids.

**Recommended action (verify, don't assume):**
1. Identify the producer of the 4 fills — engine pipeline, a manual test, or demo-account
   seeding. Check `order_router` / `ib_gateway` logs around 09:03–09:06 UTC 2026-06-01.
2. Decide the reconciliation policy: either (a) `ibkr_fills` should flow into `paper_trades`
   for a single source of truth, or (b) they are demo-account noise to be explicitly
   excluded (and the demo account should be reset/segregated before forward-test counting
   begins). Until decided, **the journal is an incomplete record of broker activity.**

---

## Part 3 — Trade Journal (past trades + going forward)

### Where trades already made live

| Table | Rows | Holds |
|---|---|---|
| **`paper_trades`** | 5 closed | Canonical simulated trade record (MCL, MES, MGC×3) |
| `ibkr_fills` | 4 | Real IB paper fills (see Part 2 — not journaled) |
| `trade_reviews` | 17 | LLM post-trade grades A–F (11 complete, 6 failed) |
| `trade_journal` | 0 | Manual mood/lesson annotations (empty, intended for human notes) |
| `journal_notes`, `trade_post_mortem` | 0 | Empty scaffolding |
| `daily_pnl`, `pnl_snapshots` | 36 each | EOD rollups / kill-switch state |

### Going forward — the auto-journal write path

1. Trade closes → `tracker.close_trade()` (`engine/portfolio/tracker.py:278`) writes
   `exit_time` + `pnl` to `paper_trades`.
2. Async task `_queue_review(trade)` fires (non-blocking, `tracker.py:433`).
3. `TradeReviewService.review_trade()` (`engine/analytics/trade_review.py:76`) writes a
   `pending` row, calls Claude Sonnet 4.6 to grade the setup, then upserts the final
   `complete`/`failed` row to `trade_reviews` (`engine/database/_mixins_reviews.py:22`).
4. Optional human annotations go to `trade_journal` (LEFT JOIN in the review query).

### What the user sees — /journal-review

- **Endpoint:** `engine/routers/journal_review_router.py` —
  `/journal/review/stats|breakdown|analyze|formalize|monthly`.
- **Query:** `SELECT pt.*, je.mood,je.note,je.lesson FROM paper_trades pt LEFT JOIN trade_journal je … WHERE pt.status='closed'`.
- **Diagnosis logic** (`_compute_stats`, lines 161-222):
  - `< 5 trades` → `insufficient_data` (no verdict possible)
  - `win_rate < 0.40` → `win_rate`
  - `avg_loss > avg_win` → `avg_loss`
  - `rr_ratio < 1.5` → `avg_win`
  - else → `solid` ("edge confirmed")
- **Dashboard:** command-center card (4 KPIs, 60s refresh) → links to `/journal-review`
  page (stats grid, by-symbol/side/regime breakdown, LLM pattern analysis, rule formalizer).

---

## Part 4 — Validation Gate: Current State + Decoupling Proposal

### Current state

Thresholds are **hardcoded** in `engine/paper/validation_gate_config.py:19-26`:
```
profit_factor=2.0, sharpe_ratio=1.5, win_rate_pct=55.0,
min_trades=60, min_days=30, max_drawdown_pct=15.0
```

Two readiness systems consume them:

- **Phase 1** (`engine/backtest/live_readiness.py`) — C1 uses a **softer 30-trade**
  bootstrap (`PAPER_MIN_TRADES=30`). C2 = a 2nd gate-v2 WFO PASS (edge proof, no paper
  accrual). C3–C7 = credential/health/kill-switch/verdict-freshness (operational).
- **Phase 3** (`engine/readiness/phase3_criteria.py`) — C1–C6 are **all edge-proof and
  require 60–100 closed paper trades over 60 days** (≥100 trades, ≥60 days, WR≥55%,
  PF≥1.5, DD≤8%, Sortino≥1.0). C7–C10 = operational stability + safety test coverage.

**The problem in one line:** Phase 3's blocking gates re-prove *statistical edge* from
paper accrual — edge that the **walk-forward / gate-v2 analysis already proved on 2+ years
of out-of-sample data** (MES_trend_rank11 = 18 OOS windows, PASS). At ~3–6 trades/year
combined, 100 paper trades is ~15–30 years away.

### What's already there (partial fidelity concept)

`engine/routers/proactive_validation_router.py:447-475` (check #8) already measures
**avg slippage vs a 1.5-tick threshold** — but it is advisory (WARN/FAIL), not a gate.
No standalone execution-fidelity validation path exists; fidelity is bundled inside the
60–100-trade edge blockers.

### Proposal — separate the two questions

**Edge proof** (already satisfied by WFO/gate-v2) ≠ **execution fidelity** (does live
execution match the backtest's assumptions?). The latter needs ~15 fills, not 100.

Define an **execution-fidelity gate** that clears forward-test once a small sample
confirms live behavior matches backtest:

| Fidelity check | Threshold | Source |
|---|---|---|
| Min fills for sample | **≥15 closed** (not 100) | `paper_trades` (+ reconciled `ibkr_fills`) |
| Avg slippage | ≤ 1.5 ticks | already computed, `proactive_validation_router.py:447` |
| Fill-price deviation vs signal | ≤ 0.05% | new |
| Broker connectivity / latency | up, ≤ 500ms | `/brokers/status` |
| Kill switch | inactive | `safety_layer` |
| Realized PF over the sample | ≥ 1.0 (sign check only, not 1.5) | sanity floor |

Then **edge** is certified by the gate-v2 verdict (already enforced via
`GATE_V2_ENFORCE_ROUTING`), and **fidelity** by this new gate. Live-readiness becomes
"edge proven on history AND execution proven on a small live sample" rather than
"re-prove edge from scratch in paper."

### Precise change points (for a future [safety-review] PR — do NOT apply unilaterally)

- `engine/paper/validation_gate_config.py:23` — keep `min_trades=60` for the *legacy*
  statistical gate; add a separate `EXECUTION_FIDELITY_GATES` dict (`min_fills=15`,
  `max_avg_slippage_ticks=1.5`, `max_fill_deviation_pct=0.05`).
- New `engine/routers/execution_fidelity_router.py` (pattern after
  `proactive_validation_router.py:447-475`) — `GET /paper/execution-fidelity/status`.
- `engine/backtest/live_readiness.py:609` — add an execution-fidelity check to the
  CHECKS list; do **not** weaken Phase 3 edge gates silently — instead mark them
  "satisfied-by-WFO" with the gate-v2 verdict as evidence.

**Safety note:** This changes what is required before live capital. It MUST be a
`[safety-review]`-tagged PR with Amo's explicit approval. Nothing here is to be
auto-applied.

---

## Part 5 — Multi-Entry Trend WFO: Scope (frequency lever)

### Why this and not more SMA/intraday variants

Every higher-frequency family already tested is a **gate-v2 FAIL** (graveyard in
`engine/data/gate_v2_verdicts/`): meanrev, donchian, gap_fade, gap_go, tpo_breakout,
tpo_reversion, confluence, and the new 15m SMA (this session). They fail because they
are the most arbitraged patterns in existence. The **only** survivors are slow SMA trend
(MES 60/200, MGC 50/120) — slow by nature. Multi-entry keeps that proven edge and adds
trades *within* a confirmed trend instead of inventing a new edge.

### What the code already supports

- `engine/backtest/trend_signals.py:117-125` **already separates trend-state from the
  entry event:** `above = (sma_f > sma_s)` is a persistent bullish/bearish state; the
  entry only fires on `cross_up = above & ~prev_above` (the 0→1 transition). The `bias`
  / `regime` columns persist across every bar of the trend — so "I'm in a confirmed
  uptrend" is already distinguishable from "I just crossed."
- `engine/backtest/position_sizer.py` has **dormant** `should_pyramid()` /
  `signal_strength_scaling()` — pyramiding scaffolding exists but is unused by trend.

### What blocks it today

`engine/backtest/backtester.py:778` gates entries on `open_trade is None` — it refuses a
new entry while a position is open. This is the one hard blocker; it assumes one position
per trend.

### Scope

**Phase 1 — signal generator** (`trend_signals.py`, ~+40 lines, medium):
add opt-in params `enable_pullback_entries=False`, `pullback_pct`, `re_entry_cooldown_bars`,
`max_entries_per_trend`; emit `PULLBACK_ENTRY` when, inside a confirmed trend and past the
cooldown, price retraces to the fast SMA then resumes. Each entry gets its own ATR stop/targets.

**Phase 2 — backtester** (`backtester.py`, ~+50 lines, **high** — Trade-lifecycle refactor):
replace `open_trade is None` with `num_open_trades < max_concurrent_positions`; track entries
per trend leg; bulk-exit all entries on the death cross.

**Phase 3 — config**: bump `max_concurrent_positions: 1 → 2` for MES/MGC in `paper_config.py`;
fix `contracts_per_entry=1` (no ATR scaling) so total per-trend risk stays ≤ 2%.

**Phase 4 — full gate-v2 re-validation** (high, computational): new WFO + Monte Carlo. The
existing `mc_95th_dd` and DSR assume one entry per signal; multi-entry changes the trade
distribution, so the verdict MUST be regenerated, not inherited.

### Risks

- Trade count multiplies (≈2–4 → ≈6–12/yr) → noisier metrics; re-validate, don't assume.
- Pullback whipsaws can concentrate drawdown in one trend leg → cap `max_entries≤3`,
  `cooldown≥3 bars`.
- Position-sizing must be pinned to fixed 1-contract entries or the backtester over-levers.

**Estimate:** 3–5 days implementation + tests; 1–2 weeks gate-v2 re-validation. This is a
proper experiment with an uncertain outcome — it may also fail the gate. It is the most
*principled* frequency lever available, not a guaranteed win.

---

## Recommended order of operations

1. **Resolve the two-ledger gap (Part 2)** — verify the 4 `ibkr_fills`, set a reconciliation
   policy. This is integrity, do it first.
2. **Decouple validation (Part 4)** — `[safety-review]` PR; correct regardless of frequency.
3. **Multi-entry WFO (Part 5)** — the real frequency project, once 1–2 are settled.
4. **Skip the graveyard** — no more SMA/intraday-variant tweaking.
