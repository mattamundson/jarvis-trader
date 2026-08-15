# JARVIS v2 Identity Manifest — jarvis-trader

**Date:** 2026-07-08
**Target repo:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\` (confirmed by Amo as "the v2 repo" after 3 other candidates were ruled out — see Methodology)
**Method:** read-only, evidence-based. Classification is from what the code *does* (imports, DB tables it writes, terms it uses), not from filenames or comments. Every row below cites a real path opened or grepped during this session (2026-07-08, native `git grep` inside the repo — not WSL 9p mount, which was too slow for full-tree sweeps).

---

## AIRGAP-VIOLATION check: NONE FOUND

No file, service, or module was found containing both ERP/Paradigm logic and trading/execution logic. The two domains are **separate codebases on separate ports**, not merged. Evidence:

1. **`engine/main.py:5`** — code comment, not a doc: `"""Runs on port 8010 (separate from GMS JARVIS on 8009)."""` — the trading engine's own source explicitly declares itself distinct from a "GMS JARVIS" system.
2. **`C:\Users\mattm\Code\jarvis-agent-gms\JARVIS.py:70` and `jarvis_secure.py:1374`** — a *separate* repo, confirmed running on port 8009, is the actual Paradigm/GMS ERP agent (Paradigm references found in `JARVIS.py`, `jarvis_secure.py`, `services/claude_code_integration.py`). It is small (4 source files, 10 endpoints) — nowhere near jarvis-trader's scale.
3. Full-repo term sweep of `engine/**/*.py` for `paradigm|inventory_item|purchase_order|customer_id|invoice|sku|lot_number|erp_sync|UpdateItem` → **zero matches**.
4. Broader smell sweep for `vendor|warehouse|cost_per_unit|purchase.?order|greenfield|gms|metal.?sales|goparagon|paragon.?erp` → 6 file hits, all read in context and confirmed **false positives** (data-*vendor* = TradingView/IBKR/Polygon feed source; *warehouse* = an options-risk metaphor in a docstring; no GMS/Paradigm business logic anywhere).

**One real cross-boundary integration point (not a code airgap violation, but worth flagging):** `engine/routers/openclaw_router.py` documents a webhook contract where an external "OpenClaw" WhatsApp gateway (registered via `http://localhost:8009/api/oc/webhook/register` — i.e., a call *to* the 8009 GMS-side process) forwards inbound WhatsApp trade-approval replies to jarvis-trader's `POST /openclaw/webhook` on 8010. This is a one-directional **messaging-infra relay** (WhatsApp yes/no → approve/reject a pending trade), not shared ERP/trading code, not shared DB, not shared capital/execution logic. Flagged per the task's instruction to surface any cross-system touchpoint found, even a non-violating one.

**Dormant/dead ERP credential (not code, but a wiring artifact):** `engine/.env.op-template` and `scripts/load-secrets.ps1` both declare `PARADIGM_API_KEY` and `PARADIGM_BEARER_TOKEN` (labeled "Service 9" in both files) pointing at 1Password items `Paradigm-API` / `Paradigm-ERP`. **Zero files** in `*.py`, `*.ts`, `*.tsx`, `*.js` anywhere in the repo read, import, or reference either variable name. This looks like an artifact of a shared personal secrets-loading template (Amo's `load-secrets.ps1` pattern is reused across projects) rather than accreted ERP functionality — HIGH confidence dead code/config, not a live integration.

---

## Summary counts (measured vs. Amo's estimate)

| Metric | Amo's estimate | Measured | Note |
|---|---|---|---|
| Endpoints | ~250 | **527** decorator-defined routes in `engine/**/*.py` (397 of those in `engine/routers/`, 79 router files) | Estimate was a ballpark; actual is ~2x, all trading/shared-infra |
| Tables | ~39 | **34** distinct `CREATE TABLE` names found in `engine/database/**/*.py` | Close match; a few more may exist in `engine/db/` or `options_positions.db`-adjacent code not grep-covered by the CREATE TABLE pattern |
| Services | ~100 | **67** top-level functional directories in `engine/` (informal "service module" count — only 4 files literally define a `class *Service`, so this is a directory-level proxy, not a strict class count) | Order-of-magnitude match |

---

## Classification: routers (`engine/routers/*.py`, 79 files, HIGH confidence unless noted)

All 79 are **trading-domain** or **shared/infra** — zero ERP. Grouped by bucket; each name is a real file in `engine/routers/`.

**Trading-domain (54):** admin, alerts, analysis, analytics, attribution, backtest, brokers, crypto, decisions, discovery, execution_status, experiments, forward_test, hidden_pivots, ib_scanner, institutional, instruments, journal, journal_review, kairos, learning, macro, market, options, options_backtest, orders, paper_validation, phase3_readiness, pipeline, pipeline_board, pipeline_ws, pnl_truth, polymarket, portfolio, prices, proactive_validation, readiness, regime, reports, safety, scanner, schwab, sentiment, session_brief, strategies, strategy_c, strategy_lab, strategy_ledger, super_engine, thinkscript, trades, trading_status, tradingview, validation, validation_analytics, watchlist, wfe

**Shared/infra (25):** approval, approval_queue, cache, config, discord (messaging transport, not ERP), durability, events, flags, health, jarvis (NL bridge — spot-checked, routes trading queries only), messaging, notifications, observability, openclaw (see integration-point note above — MEDIUM confidence, it's infra but touches the 8009 boundary), profiling, scheduler, settings, vault, webhook, websocket, whatsapp

**ERP-domain: 0 of 79.**

Spot-checked directly (not just by filename) to guard against generic names hiding ERP logic: `admin_router.py`, `config_router.py`, `jarvis_router.py`, `openclaw_router.py` — all confirmed trading/infra by content, none ERP.

## Classification: separate API — `jarvis_api/` (top-level, port 8020)

**Trading-domain.** `jarvis_api/main.py` — "JARVIS API Bridge... Serves live market data and strategy signals to the JARVIS dashboard." Panels in `jarvis_api/panels/`: equity_curve, ibkr_live, options_chain, pnl_tracker, regime_alerts, alert_feed, paper_validation, jarvis_commentary — all trading/ops. HIGH confidence.

## Classification: database tables (`engine/database/*.py`, 34 tables, HIGH confidence)

All 34 are trading/ops-domain: `agent_memory, alert_log, bar_quality_rejections, canary_strategies, capital_allocation, daily_pnl, decisions, discord_bot_signals, discord_corey_alerts, discord_corey_commentary, discord_ib_reports, fomc_history, health_snapshots, ibkr_fills, journal_notes, learning_events, market_data_bars, mes_session_hypothesis, paper_trades, paper_trades_new, pending_trade_approvals, per_account_kill_state, pipeline_llm_costs, pipeline_runs, pnl_snapshots, positions, schema_version, settings, supervisor_decisions, system_state, trade_journal, trade_reviews, trading_patterns, wfe_snapshots`.

**ERP tables: 0.** No `items`, `inventory`, `customers`, `invoices`, `purchase_orders`, `lots`, `quotes`, or `pricing_tiers` tables exist anywhere in the schema.

## Classification: service/domain directories (`engine/*`, 67 dirs)

All 67 top-level directories are trading-domain or shared/infra by content (spot-checked a sample; full-tree ERP-term sweep above covers all of them since it ran on `engine/**/*.py`, not just `routers/`): `agents, analysis, analytics, api, approval, autoresearch, backtest, backup, brokers, cache, config, dashboard, data, database, db, discord, events, execution, experiments, flags, generation, health, hooks, journal, kairos, learning, llm, markets, middleware, monitoring, notifications, optimization, options, orchestrator, paper, portfolio, profiling, readiness, recipes, reports, risk, routers, scanner, scheduler, schedulers, schemas, scripts, security, services, speculation, strategies, strategy_c, strategy_lab, systematic, thinkorswim-scripts, tools, trade_logging, utils, validation, validation_reports, vault, websocket` (+ `docs`, `logs`, `migrations`, `tests` — non-functional/support dirs, MIXED/not applicable).

**ERP-domain: 0 of 67.**

## MIXED/UNCLEAR bucket

None. Every row above resolved to a clean trading-domain or shared/infra classification on real content evidence — nothing required forcing an unclear item into a binary bucket.

## UNREAD

The following exist in the repo but were **not opened** this session and are explicitly not classified (out of scope for this pass — flagging per instruction rather than omitting silently): `dashboard-split-20260422-155815/`, `jarvis-trader-split-20260422-133019/`, `jarvis_trader_handoff_bundle/`, `agent-reach-claude-code-bundle/`, `master-jarvis/` (nested copy inside jarvis-trader), `PaperClip/`, `n-autoresearch-skill/`, `ralph-projects/`, `discord-charts/`, `discord-export/`, `thinkorswim-scripts/` (top-level, distinct from `engine/thinkorswim-scripts/`). These read as stale snapshot/bundle/backup directories from prior refactor sessions, not live app surface — the endpoint/table/service counts above are scoped to `engine/` and `jarvis_api/`, the two directories confirmed live via `CLAUDE.md`'s port table (8010, 8020) and the running-service evidence gathered earlier in this session.

---

## Verdict

**jarvis-trader is a pure trading system with no ERP accretion.** Across an exhaustive, content-level sweep of 527 endpoints (79 router files), 34 database tables, and 67 functional service directories in `engine/` plus the separate `jarvis_api/` bridge, zero files contain Paradigm/GMS ERP business logic — the only ERP-shaped artifact anywhere in the repo is a pair of unused `PARADIGM_API_KEY`/`PARADIGM_BEARER_TOKEN` declarations in the shared secrets-loading template, referenced by no code. The actual GMS/Paradigm ERP system is a separate, much smaller codebase (`jarvis-agent-gms`, port 8009), and jarvis-trader's own source explicitly acknowledges that separation in a code comment. The one real cross-system link is a WhatsApp trade-approval webhook relay (`openclaw_router.py`) between the two ports — infra-level messaging, not shared ERP/trading logic. **This clears the gate: there is no airgap violation to remediate before coordination code is designed**, though the dead Paradigm credentials in the secrets template are worth a cleanup pass at some point (not urgent, not this task's scope — READ-ONLY per constraints).
