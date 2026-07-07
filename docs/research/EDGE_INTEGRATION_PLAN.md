# Plan — Integrate X-Bookmark Edge Findings into the Jarvis Dashboard + Trading Strategy

## Context

The X-bookmark edge scan (PR #265) produced four backtested SPY/index strategies, validated on
33yr SPY through the real gate v2. Three are *real* edges, one is a documented negative:

| Strategy | What it is | Result |
|---|---|---|
| `sma12_monthly_momentum` | monthly close>12mo-SMA | Sharpe 0.95, DD −16.6% vs BH −50.8%; 3/4 CORE, DD-only fail |
| `spy_overnight_hold` | close→open drift | overnight = ~all of SPY's return; **intraday-only 0.7% CAGR/33yr** |
| `supertrend_weekly_spx` | weekly Supertrend(ATR10×3) long/cash | Sharpe 0.735>BH 0.685, DD **−27% vs −55%**; DSR 0.9998; 3/4 CORE, DD-only fail |
| `atr_band_breakout` | MA±k·ATR band | **refuted** — breakout loses; best variant DSR 0.0 → genuine FAIL |

Amo asked: what would I do next, and how do we integrate these into the Jarvis Dashboard and the
overall trading strategy? **Decisions (AskUserQuestion 2026-07-02):** primary end-goal = **futures
overlay** (regime/bias into the existing futures book — no new equity execution path near-term);
**also plan toward a separate equities book** long-term; execute the **full ladder this pass where
it makes sense** (surface + shadow-track + macro-bias overlay + gate DD-class change as a separate
Tier-3 PR).

### The strategic read (what I'd do in your shoes)

1. **These are long-biased equity (SPY) edges; the engine is a futures-only, LLM-driven intraday
   trader.** Routing SPY capital directly needs either an equity execution path or a SPY→ES/MES
   translation layer — neither exists, both are Tier-3. So the near-term win is **not** a new book.
2. **The weekly ES/SPX trend + monthly momentum edges generalize cleanly to the futures book as a
   macro-regime/bias overlay.** MES≈ES≈SPX, so the S&P's own trend directly informs the MES
   direction the engine already trades. This is the highest-value, lowest-risk integration and it's
   exactly the "futures overlay" end-goal Amo chose. The Supertrend edge's proven property (halves
   drawdown) is precisely a risk-regime filter.
3. **The overnight-drift finding is an insight, not a tradeable edge here.** It says an intraday-only
   futures posture structurally fights the risk premium (which accrues overnight). Worth surfacing,
   but `MAX_OVERNIGHT_CONTRACTS=1` is a hard safety invariant, so it stays advisory.
4. **`atr_band_breakout` stays a documented negative** (already in PR #265) — do not track or trade.
5. **Prove edges out-of-sample with zero capital first.** The engine already has the machinery:
   `engine/data/calendar_paper_track/` DARK observe-only tracks (already incl. `SPY__pre_fomc`,
   `SPY__santa_claus`). Mirror that for the two real trend edges before any capital conversation.

## Key findings from exploration (anchors the design)

- **Dashboard:** Next.js on :3010, SWR → `/api/engine/[...path]` proxy → engine :8010 (`lib/api.ts`,
  `fetchEngine`/`postEngine`). Gate verdicts render in `app/strategy-ledger/page.tsx` +
  `components/ProdGateScorecard.tsx`; richer ranked candidates at `/edge-ledger` (only `trust-pane`
  uses it); bookmark research already shown via `components/BookmarkFeedPanel.tsx`/`BookmarkThemesPanel.tsx`
  on `app/page.tsx`. Panels use `components/ui/{card,badge,table}.tsx`, Tailwind theme tokens.
- **Verdict schema** (`engine/backtest/verdict_schema.py`): requires `symbol` + `family`; read from
  `engine/data/gate_v2_verdicts/*.json`. **That dir is the production authorization dir**
  `gate_v2_policy.is_strategy_authorized` reads (PASS + `PAPER_CONFIGS[enabled]` → routes). → **Do
  NOT co-mingle SPY research verdicts there**; use a separate research namespace.
- **Promotion path:** signal-gen → `signals.generate_instrument_signals` router → `paper_runner` →
  `is_strategy_authorized` (not `VALIDATION_ONLY_INSTRUMENTS` + `PAPER_CONFIGS` enabled + fresh
  <14d gate-v2 PASS) → `approval/service.ensure_approval_allowed` → paper. Live hard-off
  (`LIVE_TRADING_ENABLED=False`, Tier-3 manual). `FUTURES_WATCHLIST="MCL,MNQ,MES"`.
- **DARK observe-only track pattern:** `engine/backtest/vwap_paper_track.py` — self-contained, re-runs
  the signal over the newest cache each tick, appends only post-inception closed trades to an isolated
  JSONL in the **main checkout** `engine/data/<name>_paper_track/`, idempotent on trade dates,
  `--report` grades forward vs backtest prior. Zero order surface.
- **Macro/bias hooks:** signal frames already emit `bias`/`regime`; live entries are LLM-driven in
  `engine/agents/pipeline.py → analyze_and_decide`. **`engine/agents/trader.py` and `engine/config.py`
  are `[safety-review]`-gated**; `engine/agents/pipeline.py` and `engine/backtest/*` are not.

## Phase 1 — Surface findings in the dashboard (visibility; zero routing risk)

Goal: the four verdicts + their bookmark provenance are visible and tracked, without polluting the
production futures ledger.

- **Research verdict namespace:** new dir `engine/data/research_verdicts/` (NOT `gate_v2_verdicts/`).
  Extend the two new runners (`run_spy_supertrend_weekly_rank1.py`, `run_spy_atr_band_rank1.py`) and
  re-emit the two Tier-A verdicts so each writes a `verdict_schema`-conformant JSON there: set
  `family` (e.g. `research_equity_trend`), populate `gate_v2_metrics` (pf_ci_lower, p_edge,
  mc_95th_dd_pct, dsr) + `gate_v2` block, add a `provenance` extra (`source_bookmark_url`, `author`,
  `scan_date`). (`extra="allow"` accepts `provenance`.)
- **New engine endpoint:** `GET /strategy/research-candidates` in a new
  `engine/routers/research_candidates_router.py` — globs `research_verdicts/`, returns rows
  {strategy, symbol, family, verdict, metrics, provenance, class_note}. Register in `engine/main.py`.
- **New dashboard panel:** `dashboard/components/StrategyResearchPanel.tsx` (mirror
  `ProdGateScorecard.tsx`: `"use client"` + `useSWR` + `Card`/`Badge`/`Table`), typed helper
  `fetchResearchCandidates()` in `dashboard/lib/api.ts`. Mount on `app/page.tsx` next to
  `<BookmarkThemesPanel/>`; add a "Strategy Research" link in `components/Sidebar.tsx` (Intelligence
  group) → new `app/strategy-research/page.tsx`. Show verdict + why-blocked + bookmark link + the
  equity-class-DD note so a FAIL reads as "class-threshold mismatch," not "no edge."

## Phase 2 — DARK observe-only forward tracks (earn a slot; zero capital)

Goal: accumulate genuine out-of-sample evidence for the two real trend edges.

- Mirror `vwap_paper_track.py` → `engine/backtest/spy_supertrend_paper_track.py` and
  `engine/backtest/spy_momentum_paper_track.py`: re-run the `generate_*_signals` over the newest SPY
  cache each tick, append post-inception closed trades to `engine/data/spy_supertrend_paper_track/`
  and `.../spy_momentum_paper_track/` (isolated JSONL + `state.json`, idempotent, main-checkout),
  `--report` grades forward vs the backtest prior.
- **Skip** `spy_overnight_hold` (gross-only, needs close/open-spread modeling) and `atr_band` (refuted).
- **Data dependency (flag in execution):** the SPY cache is static to 2026-06-24; the track advances
  only when SPY bars refresh. Add a small daily SPY-daily-bar refresh (reuse `data_loader`/Polygon)
  or note the track is dormant until cache updates. Weekly/monthly signals accrue slowly — this is
  plumbing that pays off over time.
- Optionally register frozen hypotheses in `engine/backtest/candidate_registry.json`
  (`status: forward_testing`, locked params, `lock_in_sample`) so `forward_test.py` tracks them —
  but that track is futures-trade-attributed; for equity DARK tracks the JSONL ledger is the record.

## Phase 3 — Macro-regime/bias overlay for the futures book (the primary end-goal)

Goal: turn the weekly-Supertrend + monthly-momentum edges into an advisory macro-regime context that
improves the MES/futures trader — flag-gated, shadow-logged, reversible, no risk-constant changes.

- **New module** `engine/backtest/macro_regime.py`: compute a market-wide state
  `{RISK_ON, RISK_OFF, NEUTRAL}` from agreement of (a) weekly ES/SPX Supertrend trend (reuse
  `generate_supertrend_signals`) and (b) monthly 12mo-SMA momentum (reuse
  `generate_sma12_momentum_signals`) on SPY/ES bars. Pure function + unit tests; no side effects.
- **New endpoint** `GET /macro/regime` (small router, registered in `main.py`) → surfaces the state +
  components for the dashboard and Discord (add a compact `MacroRegimeBadge` to `app/page.tsx`).
- **Advisory consumption, flag-gated:** add env flag `MACRO_TREND_BIAS_ENABLED` (default **off**) in a
  NON-`[safety-review]` location. When on, inject `macro_regime` as an **advisory context feature** at
  the pipeline layer (`engine/agents/pipeline.py` context assembly) — NOT a mechanical trade gate, and
  **do NOT modify `engine/agents/trader.py`** (that's `[safety-review]`; keep it out of this pass).
- **Shadow-log first:** before it can influence a live decision, log the would-be effect (decision/
  sizing with vs without the overlay) via the existing shadow tracker for N sessions, so the effect is
  measured before it's trusted. This mirrors the engine's own "shadow → enforce" discipline.

## Phase 4 — Equity-class gate-v2 DD threshold (Tier-3; SEPARATE gated PR)

Goal: let the three real long-equity edges eventually score PASS on a class-appropriate bar, without
loosening the intraday-futures gate. **This governs what can route to capital → Tier-3, Amo sign-off,
own PR with the `[safety-review]`-style scrutiny; not folded into Phases 1–3.**

- In `engine/backtest/_gate_v2_helpers.py`, introduce a per-strategy-class DD ceiling map (e.g.
  `STRATEGY_CLASS_DD = {"equity_swing": 0.25}`) consumed only when a verdict declares
  `strategy_class="equity_swing"`. Intraday-futures CORE (5%)/ALT (4%) defaults **unchanged**.
- Effect (from the PR #265 numbers): at DD≤25%, `sma12_monthly_momentum` + `spy_overnight_hold` pass
  CORE 4/4; ≤30% adds `supertrend_weekly_spx`; `atr_band` still fails on DSR. Also note the low-freq
  wall: monthly signals hit `MIN_OOS_TRADES_TOTAL=30` (`INSUFFICIENT_SAMPLE`) — the DARK track /
  longer sample is the honest home for those, not a threshold tweak.
- Deliver as a draft PR with the analysis, the class map, and tests; do not enable routing.

## Future roadmap (not this pass) — separate equities book

Amo also wants an eventual standalone equity/ETF sleeve. Scoped for later, gated Tier-3: build an
equity execution path + `EQUITY_WATCHLIST` + share-based sizing (precedent: `contract_specs.py` already
has SPY/QQQ/IWM `ContractSpec`; `position_sizing.py` has a price-based path for crypto to mirror), then
route the graduated DARK-track survivors as a long-biased sleeve alongside futures. This is where the
overnight and momentum edges live natively. Do NOT start until Phases 1–3 evidence justifies it.

## Safety & constraints (persist across all phases)

- Worktree-isolate all `jarvis-trader` edits; per-file staging (never `git add -A`); draft PRs only;
  never push main/master, force-push, or merge.
- **Do NOT touch** `engine/config.py`, `engine/risk/`, `engine/execution/kill_switch.py`,
  `engine/agents/trader.py`, `engine/notifications/openclaw_notifier.py`, or `engine/.env`; never flip
  `PAPER_CONFIGS.enabled`, never add SPY to `FUTURES_WATCHLIST` in this pass.
- Phases 1–2 have **zero** routing/capital surface. Phase 3 is advisory + flag-off + shadow-logged.
  Phase 4 is a separate Tier-3 PR requiring explicit sign-off (`PROPOSING_DESTRUCTIVE_OP`-style gate).
- Research verdicts live in `research_verdicts/`, never `gate_v2_verdicts/`.

## Files (create ● / modify ○)

Phase 1: ● `engine/data/research_verdicts/*.json` (4) · ● `engine/routers/research_candidates_router.py`
· ○ `engine/main.py` · ● `dashboard/components/StrategyResearchPanel.tsx` · ● `app/strategy-research/page.tsx`
· ○ `dashboard/lib/api.ts` · ○ `dashboard/components/Sidebar.tsx` · ○ `app/page.tsx` · ○ the two runners
(re-emit schema-conformant research verdicts).
Phase 2: ● `engine/backtest/spy_supertrend_paper_track.py` · ● `engine/backtest/spy_momentum_paper_track.py`
· (data-refresh helper if added) · ○ `candidate_registry.json` (optional).
Phase 3: ● `engine/backtest/macro_regime.py` (+tests) · ● `engine/routers/macro_regime_router.py` · ○ `engine/main.py`
· ○ `engine/agents/pipeline.py` (flag-gated advisory context) · ● `dashboard/components/MacroRegimeBadge.tsx` · ○ `app/page.tsx`.
Phase 4 (separate PR): ○ `engine/backtest/_gate_v2_helpers.py` (+tests).

## Verification

1. **Phase 1:** `GET /api/engine/strategy/research-candidates` returns 4 rows w/ provenance; the
   Strategy Research page renders them; **`GET /strategy/ledger` is UNCHANGED** (no research verdicts
   leaked into the production ledger); `is_strategy_authorized("SPY")` still denies.
2. **Phase 2:** run each `*_paper_track` module once (observe-only tick) + `--report`; confirm isolated
   JSONL under `engine/data/spy_*_paper_track/`, idempotent on re-run, no DB/orders touched.
3. **Phase 3:** unit tests for `macro_regime` (known bars → expected state); `GET /macro/regime`
   returns state+components; with `MACRO_TREND_BIAS_ENABLED` **off**, a pipeline dry-run is byte-identical
   to baseline (overlay inert); with it on, shadow log records would-be deltas and no live decision changes
   until reviewed. `engine/agents/trader.py` untouched (git diff).
4. **Phase 4 (separate PR):** tests show `equity_swing`-classed verdicts evaluate against the class DD
   ceiling while futures verdicts are unchanged; no routing enabled; PR carries the Tier-3 marker.
5. Full engine `/health` GREEN after router additions; `ruff --fix` clean; dashboard `tsc --noEmit`
   (`./node_modules/.bin/tsc`) clean.
