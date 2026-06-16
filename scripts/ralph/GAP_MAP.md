# GAP_MAP — US-001 Ground-Truth Verification (ralph/edge-24x7)

Verification run: 2026-06-12, engine live at `http://127.0.0.1:8010` (uptime ~3.1h, paper_mode=true).
Auth: `X-API-Key` header → validated against `settings.API_KEY` (`engine/middleware/auth.py:69`,
`engine/middleware/api_key_middleware.py:42`). Key sourced from `engine/.env` var `API_KEY` (64 chars, **redacted everywhere**).
Read-only. No source changed. No engine restart. No commit/push.

## Engine /health snapshot (no auth)
- `status=ok`, `paper_mode=true`, `live_trading=false`, `kill_switch_active=false`
- `ibkr_connected=true`, `ibkr_execution_connected=true`, **`ibkr_data_connected=false`** (data feed down — this is US-002)
- `ibgateway_alive=true`, port 4002
- `llm_providers.active_provider=anthropic`, primary_healthy=true, 3 providers configured (anthropic/gemini/openai)
- `tradingview_mcp_healthy=true`, `llm_path_healthy=true`

---

## BUILT + WORKING (feature, route/file, evidence)

| Feature | Route / file | Evidence |
|---|---|---|
| Health/liveness | `GET /health` | HTTP 200, full status blob incl. paper_mode, ibkr flags, llm provider chain |
| Today's session stats | `GET /portfolio/stats/session-today` | HTTP 200 — `{date:2026-06-12, session:EXTENDED, closed_trades:0, open_trades:1, gross_pnl:0, ...}` real & sane |
| EOD summary | `GET /paper/validation/summary/eod` (`paper_validation_router.py:578`) | HTTP 200 — `{trades_today:0, cumulative_trades:9, cumulative_pnl_usd:1291.3, validation_gates:{pf:1.65,sharpe:2.52,win_rate:22.22,...}, status:"at_risk"}` |
| 7-day performance | `GET /reports/performance/7d` (`reports_router.py:31`) | HTTP 200 — `{total_trades:2, win_rate:0.5, total_pnl:3018.18, ...}` |
| QuantStats metrics | `GET /reports/quantstats?days=90` (`reports_router.py:82`) | HTTP 200 — `{n_trades:16, source:"pnl_snapshots", sharpe:0.174, sortino:0.299, profit_factor:1.06, max_dd:-0.167, ulcer/tail/skew/kurtosis/cagr...}` (full QS blob) |
| QuantStats module import | `engine/reports/quantstats_metrics.py` | imports clean from repo root; exports `compute_quantstats_metrics`, `_load_pnl_series` |
| HTML tearsheet generator | `scripts/jarvis_tearsheet.py` | `--help` works; real run `--source paper --lookback 90` produced **488 KB HTML** at `docs/reports/tearsheets/2026-06-12_00-40_paper_paper.html` + `docs/reports/METRICS_SNAPSHOT.json` (10 gate checks printed) |
| Validation gates (live) | `GET /paper/validation/gates` (`paper_validation_router.py:489`) | HTTP 200 — 6 gates w/ current vs target (pf 1.65/2.0 fail, sharpe 2.52/1.5 pass, win_rate 22.22/55 fail, trades 9/60, days 5/30, dd 16.18/15), `overall_pass:false` |
| Discovery eval gate thresholds | `GET /discovery/evaluation/gates` (`discovery_router.py:138`) | HTTP 200 — layer1/layer2 threshold config |
| Gate v2 verdict store | `engine/data/gate_v2_verdicts/*.json` (33 files, updated 2026-06-11) | parsed: **4 PASS** (MGC_trend_rv_filter_rank1 via core; MGC_trend_adx_filter_rank1, MGC_trend_rank4, MES_trend_rank7 via alt), 2 INSUFFICIENT_SAMPLE, **27 FAIL**. PASS MGC carries full `gate_v2_metrics` (combo_results, cost_tier_results pass through "catastrophic", PF 2.53) |
| Dashboard server | `:3010` | HTTP 200; 30+ pages under `dashboard/app/` (trades, portfolio, performance, stats, validation, master, scorecard, strategy-c, **strategy-c-command**, paper, parallel-paper, journal, learning, health, watchlist, etc.) |
| Multi-channel notif primitives | `engine/notifications/{telegram.py, discord_webhook.py, discord_notifier.py, supervisor.py}` | files present & substantial (used elsewhere in pipeline) |

## BUILT BUT BROKEN / EMPTY (feature, what's wrong, error)

| Feature | Problem |
|---|---|
| `GET /reports/performance?format=html` (`reports_router.py:213`) | HTTP **503 "Database not initialized"** — the full HTML performance report route fails (the standalone `jarvis_tearsheet.py` script is the working path instead) |
| `GET /summary/eod` (bare) | HTTP **404** — does not exist at root; the real route is `/paper/validation/summary/eod`. Anything wired to `/summary/eod` is dead. |
| MAE/MFE columns | `mfe`/`mae` REAL columns exist only on the **`discord_bot_signals`** table (`migrations.py:345-346`), NOT on `paper_trades`. No per-trade excursion is captured on actual executed trades; backtester "adverse/favorable" hits are slippage-model terms, not excursion analytics. |
| Edge ledger | `engine/generation/edge_ledger.py` exists **only in an uncommitted worktree** (`.claude/worktrees/generation-engine/`), not on `ralph/edge-24x7` / master engine tree. Not importable from the running engine. |

## ABSENT (genuine gaps)

| Theme | Status |
|---|---|
| Unified "Today at a glance" tile | **Partial.** Data exists (`session-today` + `summary/eod`), but no single consolidated dashboard tile/route stitching live + traded-today + profitable-today + liveness. No `glance`/`today-tile` component found. |
| MAE/MFE + post-trade excursion analysis | **Absent on trades.** No capture on `paper_trades`, no excursion analytics endpoint/report. |
| Entry-timing scenario analysis (what-if earlier/later) | **Absent.** Only mention is a prompt heading "Layer 4 — Entry Timing" in `agents/rules/agent_prompts.py`; no scenario engine/route. |
| Multi-channel + system-down liveness alerting | **Partial.** Telegram/Discord senders exist; **no heartbeat/watchdog/dead-man "engine-down" alert** in engine/scripts. |
| Regime-conditional analysis (RISK_ON/OFF/NORMAL Sharpe slicing) | **Absent in reporting.** "regime" appears in agent reasoning, not in any report route/QuantStats slice; no RISK_ON/RISK_OFF Sharpe breakdown endpoint. |
| Highest-probability edge ledger across instruments | **Absent from live tree** (only in worktree, see above). |

---

## US-003..US-010 build verdicts

- **US-003 Unified 'Today at a glance' tile — build needed: PARTIAL.** Backing data live (`/portfolio/stats/session-today` 200, `/paper/validation/summary/eod` 200); assemble a consolidated tile — no glance component exists.
- **US-004 MAE/MFE capture + excursion analysis — build needed: YES.** `mae`/`mfe` only on `discord_bot_signals`, not `paper_trades`; no excursion analytics. Real build (capture + analysis).
- **US-005 Entry-timing scenario analysis — build needed: YES.** Nothing beyond a prompt heading. Full build.
- **US-006 Multi-channel + system-down alert — build needed: PARTIAL.** Telegram/Discord senders exist (`engine/notifications/`); missing piece = liveness/heartbeat watchdog that fires when engine is down. Build the watchdog + fan-out wiring.
- **US-007 Verify/upgrade QuantStats gates (Run-12) — build needed: PARTIAL.** Gate v2 store + `/paper/validation/gates` + `/discovery/evaluation/gates` all live and returning real verdicts (4 PASS/27 FAIL/2 insufficient); QuantStats metrics endpoint works. Upgrade/extend gate set only — core machinery already works.
- **US-008 Regime-conditional Sharpe slicing — build needed: YES.** No RISK_ON/OFF/NORMAL slicing in any report route. Full build.
- **US-009 Strategy C+ Command Center reconcile — build needed: PARTIAL.** `dashboard/app/strategy-c-command/page.tsx` + `strategy-c/` exist and dashboard serves 200; reconcile zip vs live (not greenfield).
- **US-010 Edge ledger across instruments — build needed: YES (port).** `edge_ledger.py` exists only in an uncommitted worktree, not in the live engine tree. Needs to be brought onto the branch + wired to a route/dashboard.

**Already substantially done:** US-007 (gates/QuantStats verified working). **Partial/reconcile:** US-003, US-006, US-009. **Real builds:** US-004, US-005, US-008, US-010.

---

## US-002 — Market-data feed diagnosis (2026-06-12)
- Port 4002 OPEN; gateway alive; ibkr_connected=true; ibkr_execution_connected=true; **ibkr_data_connected=FALSE**.
- Derivation: `health_router.py:417` → `ib_health.get("data_connected")`. `health_router.py:71` documents: gateway alive + data_connected=false ⇒ connector up but the IB market-data subscription/leg isn't established.
- **Not blind:** `tradingview_mcp_healthy=true` (Tier 0 for bars). `MarketDataManager.get_bars()` is TV-first, so bar data flows. The IB data leg only affects live tick-price / latency-sensitive paths.
- LLM recovered: active_provider=anthropic, primary_healthy=true (no longer on Gemini fallback).
- **Root cause (likely):** IB market-data farm/subscription not initialized for the paper account this session (common outside RTH or after a data-farm drop). **Fix (Amo-gated):** reconnect IB data / verify market-data subscription, or run the engine restart helper to re-establish the data leg. Bars remain covered by TV MCP meanwhile.
- **Verdict:** Operational, not a code bug. No autonomous restart. Bar-driven edge/backtests trustworthy; live tick pricing degraded until the data leg reconnects.
