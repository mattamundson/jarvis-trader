# JARVIS TRADER — Master Completion Roadmap

**To: fully-resolved, fully-autonomous production system**
**Created:** 2026-07-21 · **Owner:** Amo · **Format:** living checklist — check items off as they land.

> Consolidates and supersedes the partial `docs/ROADMAP_TO_AUTONOMOUS_2026-07-21.md` (which covered only the supervision phase). Grounded in a 10-agent subsystem survey (execution, LLM, dashboard, monitoring, autonomy/learning, analytics, peripheral agents) + `CURRENT_STATE.md`.

---

## The one finding that orders this whole plan

**The live decision pipeline never places a real IB order.** `SafetyLayer._ib_gateway` is bound to the pure-Python `IBGatewayConnector` **simulator** (`main.py:476`), not the real `IBGatewayManager` (the README's designated "single front door"). `FuturesMarketModule.execute_signal()` — the only path to the real connector — is a hardcoded stub. Consequences that cascade through every subsystem:

- Paper "fills" are simulated in-process, and the phantom mock-quote table can fabricate them when data is blind (the recurring ~5300 MES bug).
- Stop-losses booked in the sim are not real resting orders → a naked-position monitor has nothing real to check.
- There is **no execution surface to flip** for the paper→live cutover described in `CURRENT_STATE.md`.

So Phase 0 is **data + execution integrity**. Everything else (autonomy, monitoring, live capital) is built on it and is not trustworthy until it's done.

**Legend:** `[safety-review]` = requires the safety-review PR tag + Tier-3 sign-off. `⛔blocker` = gates later phases. `🔬validation` = a proof/test task, not a build task.

---

## PHASE 0 — Data & Execution Integrity (foundation)

*Nothing measured on top of fabricated fills or a split ledger is real. This phase is prerequisite to ALL validation and autonomy work.*

- [ ] **0.1 — Deploy the phantom-quote fix.** ⛔blocker
  Merge `fix/refuse-phantom-mock-quotes` (`9170944`, `f7f9d91`) to the deployed branch; confirm `ALLOW_MOCK_QUOTES` defaults `False` in the running `.env`.
  *Files:* `engine/execution/ib_gateway_connector.py` (mock table ~1188-1224, `no_price_basis` reject ~604-640), `engine/execution/paper_trade_logger.py`.
  *Acceptance:* a fill for a currently-blind symbol is **rejected** (`status=rejected`, `reason=no_price_basis`), never booked at a frozen mock price; a pytest run writes zero fixture rows to the ledger.

- [ ] **0.2 — Decide & wire the single authoritative order path.** ⛔blocker `[safety-review]`
  Choose (a) wire `FuturesMarketModule.execute_signal()` → `IBGatewayManager.place_paper_order()` gated by `ALLOW_PAPER_SIMULATED_ORDERS`, routing the primary pipeline's approved trades to the real IB paper account; or (b) formally declare `IBGatewayConnector` the permanent paper mechanism and `ib_gateway.py` an audit-only channel. This decision blocks every live-cutover task.
  *Files:* `engine/markets/futures/module.py:219-229`, `engine/main.py:476`, `engine/risk/safety_layer.py`.
  *Acceptance:* a written architecture note (in the PR) naming the authoritative connector, reviewed under `[safety-review]`; `PAPER_SOURCE_OF_TRUTH.md` updated to match reality.

- [ ] **0.3 — Collapse the two-ledger divergence to one source of truth.** ⛔blocker
  Reconcile the SQLite `paper_trades` ledger against the paper-runner JSON; pick one authoritative writer/reader and make the other derive from it or die.
  *Files:* `scripts/reconcile_paper_sources.py`, `docs/runbooks/PAPER_LEDGER_BOUNDARIES.md`, `engine/portfolio/tracker.py`.
  *Acceptance:* `python scripts/reconcile_paper_sources.py` reports **zero** divergent rows; one ledger is documented as canonical.

- [ ] **0.4 — Stop pytest from writing the production ledger (hermetic isolation at the data layer).**
  The fixture-price contamination since 2026-05-06 came through here; lock it shut.
  *Files:* `engine/execution/paper_trade_logger.py` (pytest-isolation guard ~94-110), plus the `config.py` `load_dotenv(override=True)` issue tracked in 6.1.
  *Acceptance:* a full `pytest` run leaves `paper_trades` byte-identical (checksummed before/after).

- [ ] **0.5 — Purge phantom-contaminated history & restart paper from clean zero.** `[safety-review]`
  Archive (never delete) the contaminated ledger + any fabricated Strategy-C artifacts to `~/Archive/2026/jarvis-phantom-quarantine/`; re-baseline paper trading.
  *Acceptance:* the active ledger contains only post-fix, real-price fills; equity/P&L recomputed from the clean set.

- [x] **0.6 — Add plausibility filtering to every trade-derived stat consumer.** — done, `63cd227`
  Route `confidence_scorer._fetch_symbol_trades` and `consolidator._fetch_trades` through `analytics/outcome_hygiene.is_plausible_pnl()` (already protects the Brier table but NOT these).
  *Files:* `engine/learning/confidence_scorer.py`, `engine/learning/consolidator.py`, `engine/analytics/outcome_hygiene.py`.
  *Acceptance:* a synthetic >$5000-abs-P&L row is excluded from both `get_confidence_adjustment` and `consolidate_daily` in a unit test.

- [ ] **0.7 — Remove/fence the dead third IB implementation.** `[safety-review]`
  `engine/execution/ibkr_executor.py` is a third independent `IB()` connection with **no live-port safety guard** and a latent MCL contract bug; unreferenced except by its own test. Archive it, or add the `LIVE_TRADING_PORTS` guard + fix the contract logic if kept.
  *Acceptance:* `grep ibkr_executor` returns only an archive path or a guarded+tested+referenced module.

- [ ] **0.8 — Real-time / fill-time phantom guard (not just daily-batch).**
  `phantom_detector` runs only at EOD (20:05 UTC) and is flag-only. Add a fill-time sanity check (entry/exit excursion, price-basis presence) that refuses the fill in the moment, complementing 0.1.
  *Files:* `engine/analytics/phantom_detector.py`, `engine/execution/ib_gateway_connector.py`.
  *Acceptance:* a fabricated fill is blocked at submission, not discovered hours later.

---

## PHASE 1 — Decision Integrity (make the brain honest)

*The pipeline can only be as good as its scoring and its provider reliability. Fix the corrupt signals before amplifying autonomy.*

- [ ] **1.1 — Fix the inverted Brier / agent-trust scoring rule.** ⛔blocker `[safety-review]`
  Below |signal|=0.5 the current rule rewards abstention and punishes conviction; it corrupts the debate-stage trust weights. Replace conviction-vs-correctness with a real signal→probability calibration map (monotonic curve fit on realized outcomes).
  *Files:* `engine/analytics/ic_ensemble.py` (`compute_brier` ~569), `engine/agents/debate.py:487-522`.
  *Acceptance:* unit test — a high-conviction-correct agent scores strictly above both an abstainer and a high-conviction-wrong agent.

- [ ] **1.2 — Confirm Signal D actually runs in production.** ⛔blocker 🔬validation
  Memory says PR #449 merged to master but Signal D "never ran in the live checkout." Verify the live checkout contains it and it fires.
  *Acceptance:* a live pipeline run shows Signal D contributing (log/DB evidence), or a task to wire it if absent.

- [ ] **1.3 — Deploy the Kimi last-resort LLM fallback.**
  Commit `f9805f3` is committed on `fix/refuse-phantom-mock-quotes`, not deployed. Restart the engine to load it (gated on the Phase-0 merge so it ships together).
  *Acceptance:* engine boot log shows `kimi=enabled`; `/health/llm` lists kimi as the terminal fallback leg.

- [ ] **1.4 — Widen cross-provider failover beyond credit-exhaustion.** ⛔blocker
  Today only the literal string "credit balance is too low" triggers the Vertex→Gemini→OpenAI→Kimi cascade. A rate-limit storm, 5xx, or auth failure exhausts the Anthropic chain and dies with every other provider unused. Factor the cascade into a shared helper called from all three Anthropic except-blocks.
  *Files:* `engine/llm/client.py` (RateLimit ~1161, APIStatus ~1184, `_is_credit_exhaustion` ~173).
  *Acceptance:* a persistent `RateLimitError` (no credit string) is proven to reach Gemini/OpenAI before failing, in a new test.

- [ ] **1.5 — Enforce an LLM daily-cost ceiling.** `[safety-review]`
  Cost is logged but never capped. Add a configurable daily ceiling that degrades to the cheapest tier (not a hard block that would stop mid-day trading) on breach, sharing the threshold with `/health/llm.cost_warning`.
  *Files:* `engine/llm/cost_tracker.py`, `engine/llm/client.py` (`call()` head), `engine/config.py`, `.env.example`.
  *Acceptance:* a stubbed over-ceiling total downgrades the next call to fast tier in a unit test.

- [ ] **1.6 — Resolve the enrichment-tier provider billing (dedicated keys).** ⛔blocker
  Gemini AI-Studio spend-capped, OpenAI quota-dead, and Hermes shares jarvis-trader's Gemini key (confirmed SHA256 match) — a single billing point of failure keeps `/health` at `degraded`. Split a dedicated Gemini key, raise/right-size the cap, restore OpenAI quota.
  *Acceptance:* `/health` reads `ok` (not `degraded`) with all three analyst providers reachable; Hermes on its own key.

- [x] **1.7 — Close the review→improve learning loops (three dead-ends).** — code dead-ends closed, `a458491`. feedback→patterns wired (also fixed `patterns._upsert` which was async-only and silently no-op'd against the live SYNC manager — `_maybe_await` shim); post_mortem wired into `close_trade` behind `JARVIS_POST_MORTEM_ON_CLOSE` (default OFF — Opus/close is a cost opt-in). 5/5 hermetic tests. **Deferred to Amo:** sub-bullet 3 (`trade_review` grades → agent weights) is a decision-integrity design call, not autonomous-safe; and full close_trade→both-rows integration (both fire-and-forget hooks sit behind the `TESTING` guard, so it's asserted at the function boundary, not through a live cycle).
  - `learning/feedback.process_trade_outcome()` generates a lesson and drops it → call `patterns.update_patterns_from_feedback()` so the rich 10-pattern extractor runs on every close.
  - `agents/post_mortem.PostTradeAnalyzer` is never invoked after a trade closes → wire it into `tracker.close_trade()` so `self_audit.py`'s weekly report stops running on empty post-mortems.
  - `analytics/trade_review.py` grades sit in a dashboard-only table → decide whether/how they feed agent weights.
  *Files:* `engine/learning/feedback.py`, `engine/learning/patterns.py`, `engine/agents/post_mortem.py`, `engine/portfolio/tracker.py:479-552`, `engine/agents/self_audit.py`.
  *Acceptance:* a closed paper trade produces a new `trading_patterns` row AND a `trade_post_mortem` row within one cycle; integration test asserts both.

- [~] **1.8 — Retire or wire the dead cost/caching systems.** — skill-doc half done, `6d491a0` (fixed the stale `route_model()`/`get_client()`/`client.messages.create()` refs → real `route_task`/`JarvisLLMClient.call`; import-checked clean against the venv). **Deferred to Amo:** the caching retire/wire half — picking `token_optimizer` vs `context_manager`, wiring into `main.py`'s `TradingPipeline`, and proving `cache_read_input_tokens>0` — is a design decision + live LLM-path change + credit-gated verification (Anthropic credits are dead).
  Prompt caching is built twice (`token_optimizer.py`, `context_manager.py`) and wired zero times — `main.py:905` constructs `TradingPipeline` without a context manager, so caching never happens in prod. Pick one, wire it (with a content-type guard so list-of-blocks content isn't `str()`-stringified into Gemini/Kimi), archive the other. Fix the stale `jarvis-cost-routing` skill's `route_model()`/`get_client()` references (they don't exist).
  *Acceptance:* a live Anthropic call shows `cache_read_input_tokens > 0` on a repeat system prompt; skill doc import-checks clean.

---

## PHASE 2 — Safety & Risk Hardening (must be GREEN before any real capital)

- [ ] **2.1 — Drive the real-money-readiness gate to GO.** ⛔blocker 🔬validation
  The `real-money-readiness` loop (DAILY 10:00, report-only, 7 hard gates) is currently NO-GO with ~6 blockers. Enumerate each gate + blocker from its code, and close them one by one; most map to tasks in Phases 0–4.
  *Acceptance:* the loop reports GO with all 7 gates passing for N consecutive days.

- [ ] **2.2 — Build the naked-position continuous invariant monitor.** ⛔blocker `[safety-review]` (blocked on 0.2)
  A restart currently drops the kill-switch's cancel-all capability silently; there is no continuous check that every open position has a live protective stop. Build one — but it needs real resting orders (0.2) to check against.
  *Files:* new `engine/services/bracket_invariant_monitor.py`, wired in `main.py` lifespan.
  *Acceptance:* an open position without a real stop pages within 60s and self-heals a protective stop.

- [ ] **2.3 — Durably persist OMS bracket state.**
  `OMSManager.active_trades` is in-memory only; `reload_from_db()` assumes an unverified method and can't restore `stop_loss_id`/`take_profit_id` → OCO linkage lost across restart.
  *Files:* `engine/execution/oms_v2.py`, DB migration.
  *Acceptance:* kill engine mid-bracket, restart, OCO linkage restored and cancellation still works.

- [ ] **2.4 — Feed-loss-with-open-risk behavior (SOFT_HALT vs flatten).** `[safety-review]`
  Undesigned behavior at the moment risk is highest (data feed dies while positions are open). Design + implement the branch.
  *Acceptance:* a simulated feed-loss with an open position triggers the chosen protective action deterministically, tested.

- [ ] **2.5 — Reconcile the safety-limit source of truth.**
  Two canon docs disagree (-2%/-10% vs -6%/-20%); the dashboard hardcodes -2%/-10% and a 40-orders/min gauge (real limit is 10 — 4× too permissive). Establish `engine/.env`/`config.py` as the one source and expose it via `/safety/status` (or a new `/safety/limits`).
  *Files:* `engine/config.py`, `engine/risk/safety_layer.py`, `engine/routers/safety_router.py`.
  *Acceptance:* one endpoint returns the live limits; docs + dashboard both read from it (see 5.2).

- [ ] **2.6 — Kill-switch drill.** 🔬validation
  `CURRENT_STATE.md` success criteria require the kill switch tested ≥5 times. Run scripted drills (daily-loss halt, drawdown halt, manual halt, consecutive-loss ladder).
  *Acceptance:* ≥5 documented activations, each halting new orders and surfacing on the dashboard.

---

## PHASE 3 — Observability & Self-Healing (24/5 unattended)

- [ ] **3.1 — Deploy the already-built down-alert.** (cheapest, do first)
  `scripts/ops/down-alert.mjs` + `durability.mjs` are fully built and documented but never deployed (no pm2 entry, no state files). Add the entry per `ENGINE_DOWN_ALERTING.md`.
  *Acceptance:* kill engine → one Discord DOWN alert + one RECOVERED on restart; `down_alert_events.jsonl` gets a row.

- [ ] **3.2 — Fix pm2 durability.**
  `jarvis-engine` has `min_uptime:"10s"` vs a ~229s real startup → a crash-loop reads as "stable" for ~219s. Raise to ~300s, add backoff, add `/health/ready`.
  *Files:* `engine/ecosystem.config.js`.
  *Acceptance:* delete `dump.pm2`, confirm regeneration; reboot the machine and confirm unattended recovery.

- [ ] **3.3 — Unify watchdogs + build a real pager.** `[safety-review]`
  Five independent watchdogs, no shared severity/dedup/incident ledger, and no ack layer anywhere. Build `engine/ops/supervision.py` (failure-mode table) + `notifications/pager.py` (repeat-until-ack) + a SQLite incident ledger.
  *Acceptance:* chaos drills — a self-healing event stays quiet; an IB-down-with-open-position pages within 60s and repeats until acked.

- [ ] **3.4 — Enable predictive maintenance in alert-only mode.**
  Fully built + tested but `ENABLE_PREDICTIVE_MAINTENANCE=0` in live `.env`. Flip to `1`, keep `PREDICTIVE_MAINTENANCE_ALLOW_RESTART=0`.
  *Acceptance:* `/health/predictive` shows `enabled:true` and accrues degradation-score history with zero unintended restarts.

- [ ] **3.5 — Health-honesty sweep.**
  Kill the "green while blind" instances: unconditional "Telegram poller started" log when `TELEGRAM_POLLER_ENABLED=false`; `/health/apis` reading cached `ibkr.is_connected` instead of a round-trip; retire the fail-open dead `engine/health/ib_monitor.py`.
  *Files:* `engine/main.py:2918`, `engine/routers/messaging_router.py:442`, `engine/routers/health_router.py`, `engine/health/ib_monitor.py`.
  *Acceptance:* every health field reflects a real probe; no fail-open path remains reachable.

- [ ] **3.6 — Single-pane-of-glass `/health/assertions`.**
  One endpoint of N binary assertions so the dashboard renders rather than re-derives across ~10 `/health*` routes.
  *Acceptance:* dashboard reads one endpoint; each assertion maps to a real subsystem probe.

- [x] **3.7 — Reconcile stale ops docs.** — done, `f48aaa3`. Fixed kill-switch numbers (-2%/-10% → live -8%/-20% from `.env`) + added a Telegram/HERMES delivery-path status banner (gateway stopped 2026-07-20). **Surfaced:** `.env` drifted from config.py defaults (0.08 vs 0.06 daily, 1000 vs 100 USD) — reconciling those is `[safety-review]`, left for Amo.
  `AUTONOMOUS_MONITORING_SYSTEM.md` cites dead kill-switch numbers and a possibly-dead Hermes/Telegram channel (gateway stopped 2026-07-20). Verify live state, update.

---

## PHASE 4 — Autonomy Loop Closure (prepare→decide→execute→review→improve)

*The loop is ~90% on PREPARE, ~85% DECIDE, but IMPROVE is ~40% — several stages are open loops or dead code.*

- [ ] **4.1 — Make phantom detection enforcing (opt-in).** `[safety-review]`
  Add `PHANTOM_DETECTOR_ENFORCE` (default off): when on, suspect trades are auto-excluded from confidence-scorer/consolidator/forward-test inputs without a manual `mark_phantom_trades.py` run (detection stays non-destructive to the ledger).
  *Acceptance:* with the flag on, a suspect trade is provably absent from `get_confidence_adjustment` and forward-test stats.

- [ ] **4.2 — Wire nightly strategy discovery into the candidate registry.**
  `strategies/discovery_loop.py` ELIGIBLE verdicts die at a log line. Register them as *pending* candidates so they enter the gate-v2 + forward-test funnel.
  *Files:* `engine/strategies/discovery_loop.py:220`, `engine/backtest/candidate_registry.py`.
  *Acceptance:* an ELIGIBLE nightly strategy appears in the candidate-review surface within 24h; human approval still required to deploy.

- [ ] **4.3 — Forward-test graduation queue.**
  `forward_test.py` computes `graduated` with real rigor (BH-FDR, DSR, trade-shuffle) but nothing consumes it — only a Discord ping that can be missed. Persist graduation candidates to a durable reviewable queue.
  *Files:* `engine/schedulers/eod_scheduler.py:802`, `engine/backtest/forward_test.py`, new router endpoint.
  *Acceptance:* a graduated candidate is queryable a week later even if the notification was missed.

- [ ] **4.4 — Wire the capital allocator.**
  `orchestrator/capital_allocator.py` is never instantiated; the nightly rebalance branch is dead. Inject it into `EODScheduler`; confirm real per-symbol Sharpe (not the flat fallback).
  *Files:* `engine/main.py:1675-1687`, `engine/orchestrator/capital_allocator.py`.
  *Acceptance:* nightly log shows differentiated per-symbol allocations; unit test confirms MES≠MGC weight when Sharpe differs.

- [ ] **4.5 — Wire the systematic executor behind a graduated-autonomy flag.** `[safety-review]`
  `systematic/live_signal_executor.py` is self-documented dead. Add a scheduled task that, only for a human-marked `deployed_live` candidate, calls `execute_signal()`; `SYSTEMATIC_AUTO_EXECUTE` stays default-off.
  *Acceptance:* with the flag on + one test candidate, a signal produces exactly one paper order, idempotent on re-run, no double-fill vs the autonomous queue (dedup verified).

- [ ] **4.6 — Formalize the graduated-autonomy ladder.** `[safety-review]`
  Document + implement the state machine:
  - **Tier 0 Approval-required** (live default) — every decision → human approve/reject.
  - **Tier 1 Auto-approve-paper** (live for MES today) — expand to MGC only after MGC has a ≥20-trade clean (0.6-filtered) sample + sane confidence adj + gate-v2 ALT PASS.
  - **Tier 2 Supervised-live** (missing) — graduated candidates route to real orders with a mandatory daily human digest + kill-switch-only intervention (not per-trade approval). Design what "supervised" gates on.
  - **Tier 3 Autonomous-live** — `LIVE_TRADING_ENABLED=True`; human Tier-3 call, never auto-enabled.
  *Acceptance:* each tier is an explicit, documented config state with defined promotion criteria.

- [ ] **4.7 — Deduplicate the two approval-queue schemas.**
  `pending_trade_approvals` (manual path) and `pipeline_approval_queue` (autonomous path) coexist; an audit reading one misses the other. Converge or document a single read surface.

---

## PHASE 5 — Trader Console (the human surface; trader-first)

- [ ] **5.1 — Consolidate to one approval UI and make it the flagship's.** ⛔ (safety-critical UX)
  Three implementations with divergent guardrails; the safest (`trades/pending-approvals` — confirm dialog + required price-override + live risk summary) is NOT the default surface, while `/command-center` uses a one-click no-confirm panel. Consolidate to the safe one; archive the others.
  *Files:* `dashboard/components/ApprovalPanel.tsx`, `PendingApprovals.tsx`, `dashboard/app/trades/pending-approvals/page.tsx`, `dashboard/app/command-center/page.tsx`.
  *Acceptance:* one approval component; a Playwright e2e drives approve AND reject and asserts the engine call + row removal.

- [ ] **5.2 — Fix the numeric bugs & wire limits live.**
  Orders/min gauge hardcoded `/40` (real limit 10); daily-loss/drawdown labels hardcoded. Read all from the 2.5 endpoint.
  *Files:* `dashboard/app/command-center/page.tsx` (~437, ~752-763, ~956-1013).
  *Acceptance:* gauge denominators + threshold labels match live `config.py`/`.env`, verified against `/safety/status`.

- [ ] **5.3 — Consolidate the kill-switch control.**
  One typed-"CONFIRM KILL" component (`components/KillSwitch.tsx`) replacing the bare `confirm()` and two duplicated `KillSwitchPanel` functions.
  *Acceptance:* one component in three places; e2e exercises typed-confirm activate + two-click deactivate.

- [ ] **5.4 — Delete or fix `OrderEntryPanel.tsx`.**
  Dead code that POSTs directly to `/orders/place` (bypassing the pipeline) with risk math hardcoded to a 5000 reference price and ×50 multiplier. Archive it, or rebuild against live prices + real contract specs and route through the approval pipeline.
  *Acceptance:* file gone from the live tree, or its numbers verified against a hand-computed value for MES + one non-MES symbol.

- [~] **5.5 — Orphan-component reconciliation.** — audit done, `b422115` (`docs/dashboard-orphan-audit.md`): 69/200 true orphans, reliable directory-scoped git grep. Found the roadmap's own `RiskStatusWidget` "retired" claim is stale (still referenced by `app/paper/page.tsx`). **Deferred to Amo:** archiving 69 files is a destructive batch needing WIP-vs-dead triage + `pnpm run build` verification per batch — not autonomous-safe.
  Every component in `dashboard/components/` is imported from a route or archived (`RiskStatusWidget` retired-per-comment, `EnginePnlTruthCard` well-built-but-unreached, `CircuitBreakerPanel`, `ExecutionCockpitWidget`, etc.).

- [ ] **5.6 — Mission Control approval visibility.**
  The "fused" risk+trading page has zero pending-approval visibility. Add a count/link or document the deliberate exclusion.

---

## PHASE 6 — Test & Release Engineering (money-handling confidence)

- [ ] **6.1 — Fix test hermeticity (`load_dotenv(override=True)`).** ⛔blocker
  `config.py:29` pulls the LIVE `engine/.env` into every pytest process, so non-hermetic tests route to REAL live LLM calls (observed ~$0.007 real spend, health never flipping). Scope how many tests are affected; make the fixture layer clear provider env deterministically (as already patched in a few LLM tests) or stop overriding in test context.
  *Acceptance:* the full suite runs with zero real network LLM calls (assert via a call-counter/monkeypatch guard); no test inherits `JARVIS_DECISION_PRIMARY`/`MOONSHOT_API_KEY`.

- [ ] **6.2 — End-to-end numeric-accuracy test (engine→proxy→render).** ⛔blocker 🔬validation
  The documented known gap. One test hits a real/realistic engine, captures raw JSON, and asserts the rendered DOM value for realized P&L, win rate, one position's unrealized P&L, and the kill-switch daily-loss %.
  *Files:* new `dashboard/tests/e2e/`, extend `scripts/check-live-data.mjs`.
  *Acceptance:* CI fails if engine↔dashboard values diverge beyond epsilon.

- [ ] **6.3 — CI pipeline that gates merges.**
  A real CI (GitHub Actions or equivalent) running engine pytest + dashboard build + secret scan, blocking merge on red. Today enforcement is local pre-commit only.
  *Acceptance:* a PR with a failing test cannot merge.

- [ ] **6.4 — Coverage targets + dashboard tests.**
  Set coverage floors for safety_layer / pipeline / execution / signals; add dashboard unit + e2e coverage (currently minimal).
  *Acceptance:* coverage report meets the floor; dashboard has runtime (not just type-level) tests.

- [ ] **6.5 — Release checklist / preflight.**
  A documented, scripted release procedure (bump `pipeline_version`, run `/system/preflight`, verify `/health` gates, tag).
  *Acceptance:* a dry-run release passes preflight with a green checklist.

---

## PHASE 7 — Validation & Forward Testing (the proof before live)

*This is the evidence Amo needs to make the Tier-3 live call with real, clean data.*

- [ ] **7.1 — Clean-data paper validation window.** 🔬validation ⛔blocker
  With Phases 0–1 done, run an uninterrupted paper window on MES + MGC against the success criteria: PF > 1.5, Sharpe > 1.0, Max DD < 10%, Win Rate > 45%, 99.5% broker uptime, 0 unhandled exceptions.
  *Acceptance:* all metrics met over the defined window on clean (non-phantom) trades.

- [ ] **7.2 — Re-run WFO + gate-v2 on the clean sample.** 🔬validation
  Re-score each active instrument/strategy through gate v2 (pf_ci_lower≥1.10, p_edge≥0.95, mc_95th_dd≤5%/4% ALT, dsr≥0.10) with the corrected scoring and clean data.
  *Acceptance:* each promoted instrument PASSES gate v2 on the clean re-run; `/validation` scorecard reflects it.

- [ ] **7.3 — Turn the shadow statistical gates into hard gates.** `[safety-review]` 🔬validation
  `permutation_test` / `mcpt_power` / `oos_access_ledger` are intentionally diagnostic-only; DSR is not yet in `composite_score`. Wire the trade-sign permutation gate + DSR + OOS cap enforcement (`OOS_CAP_ENFORCE`) as blocking, per the deferred `[safety-review]` plan.
  *Acceptance:* a strategy failing the permutation/DSR/OOS gate is refused promotion automatically.

- [ ] **7.4 — Forward-test graduation, proven end-to-end.** 🔬validation
  A candidate graduates through 4.3's queue, a human promotes it, and it trades supervised (4.6 Tier 2) — the full prepare→decide→execute→review→improve loop demonstrated on one real candidate.
  *Acceptance:* one candidate traverses discovery→registry→gate→forward-test→graduation→supervised-paper with evidence at each hop.

- [ ] **7.5 — Application review / red-team pass.** 🔬validation
  A full adversarial review of the money path: order lifecycle, partial fills, reconnection, reconciliation, kill-switch, approval flow, and numeric parity — before any live capital.
  *Acceptance:* a written go/no-go review with every finding resolved or explicitly accepted.

- [ ] **7.6 — Partial-fill & reconnection handling.** (surfaced by 7.5, often missing)
  No partial-fill model exists anywhere in `execution/`; add `filled/remaining` to `BracketOrder` + the fill path; harden IB reconnection edge cases.
  *Acceptance:* a simulated 2-of-3 fill updates OMS state without orphaning the remainder; reconnection under load tested.

---

## PHASE 8 — Live Cutover (Tier 3, human-gated — never automated)

- [ ] **8.1 — Live-unlock ritual.** `[safety-review]` — an explicit, logged, reversible procedure to move `IBKR_PORT` 4002→4001 (keep the hard block in `ib_gateway.py`; add a signed config flag + startup banner, not a code weakening). Requires Tier-3 sign-off.
- [ ] **8.2 — Reconcile against the live account** (`PositionReconciler` + `IBKRReconciler`) before the first real order.
- [ ] **8.3 — Position-size ramp** 0.25x → 0.5x → 1.0x over weeks 1–3, with `REQUIRE_HUMAN_APPROVAL=True` held through week 1.
- [ ] **8.4 — Supervised-live → autonomous-live** promotion only after the ramp completes clean and the readiness loop (2.1) stays GO.
- [ ] **8.5 — Live fidelity measurement** — daily slippage/fidelity stats against the real fill mechanism, surfaced to the dashboard.

---

## Dependency spine (critical path)

```
0.1 phantom fix ─┐
0.2 real order path ─┼─► 2.2 naked-position monitor ─┐
0.3 single ledger ──┘                                 │
0.6 plausibility ───► 1.1 Brier fix ──► 4.x autonomy ─┼─► 2.1 readiness GO ──► 7.x validation ──► 8.x live
1.4 LLM failover ───► 1.6 provider billing ───────────┘
6.1 hermeticity ────► 6.2 e2e numeric ──► 6.3 CI ─────────────────────────────► 7.5 app review
```

**Do-first (cheap, unblocking):** 0.1, 3.1, 3.2, 1.3, 6.1.
**Highest-leverage (everything hangs off these):** 0.2 (real order path), 1.1 (Brier), 2.1 (readiness gate).

---

## Known-issue → task map (nothing dropped)

| Known issue | Task |
|---|---|
| ~5300 MES phantom mock-quote | 0.1, 0.8 |
| Two-ledger divergence | 0.3 |
| pytest contaminating prod ledger | 0.4, 6.1 |
| Pipeline never places real order | 0.2 |
| Dead `ibkr_executor.py` (no live guard) | 0.7 |
| Brier scoring inverted | 1.1 |
| Signal D never ran in prod | 1.2 |
| Kimi fallback committed not deployed | 1.3 |
| LLM failover credit-exhaustion-only | 1.4 |
| Gemini cap / OpenAI quota / Hermes shared key | 1.6 |
| Dead learning loops (post_mortem, patterns) | 1.7 |
| real-money-readiness NO-GO/6 | 2.1 |
| No naked-position monitor | 2.2 |
| down-alert built-not-deployed | 3.1 |
| pm2 min_uptime 10s vs 229s | 3.2 |
| Predictive maintenance off | 3.4 |
| Approval UI one-click no-confirm | 5.1 |
| Orders/min gauge 4× too permissive | 5.2 |
| No e2e numeric test | 6.2 |
| Test hermeticity (load_dotenv) | 6.1 |
```
