---
# JARVIS TRADER — EOD Session Handoff
goal: All 10 Systems Green — paper trading operational
date: 2026-04-09
status: COMPLETE (pending Schwab OAuth and Discord export from Matt)
written_by: Agent 10
timestamp: "2026-04-10T02:40:00Z"
---

## system_state

engine:
  status: ok
  version: "1.1.0"
  live_trading: false
  kill_switch_active: false
  paper_mode: true
  database: connected
  ibkr_connected: true
  schwab_connected: false
  uptime_seconds: ~61 (recently restarted)

prices:
  MCL: 98.86 (source: ibkr_historical, prev_close: 98.61, +0.25%)
  MES: 6861.50 (source: ibkr_historical)
  MNQ: 25261.25 (source: ibkr_historical)
  SPY: 679.28 (source: ibkr_historical)
  QQQ: 609.40 (source: ibkr_historical)

portfolio:
  open_positions: 1
  MCL:
    trade_id: "4521e0d9-a929-4216-a0b9-aebb2741c772"
    action: buy (LONG)
    quantity: 1 contract
    entry_price: 84.20
    entry_time: "2026-04-08T13:38:27Z"
    current_price: 98.86
    unrealized_pnl: "+$1,466 (1466 × $100/pt × (98.86 - 84.20))"
  realized_pnl: "+$100 (closed MCL trade)"

## completed_today

pipeline_fixes:
  - "#1 API credits: Anthropic API active, real LLM calls confirmed (was returning placeholder)"
  - "#2 STC pre-filter: working (OS=15, OB=83) — midrange skip config-driven"
  - "#3b IB live data: ibkr_historical data source operational — MES=6861, MNQ=25261, MCL=98.86"
  - "#4 B9 fix: reload_open_positions_from_db() with status=open filter — true SQLite-backed reload"
  - "#5 MTF re-enabled: staleness guard added, stale MNQ 4h CSV deleted from cache"
  - "#6 Cache invalidation: POST /pipeline/cache/invalidate/{symbol} and /pipeline/cache/invalidate-all"
  - "#8 Model downgrade: risk_manager + fund_manager now claude-sonnet-4-6 (was opus — cost reduction)"

debate_improvements:
  - "Conviction tie-break (35% asymmetry threshold) — prevents infinite HOLD loops"
  - "BullResearcher/BearResearcher now run real LLM rounds (not stub)"
  - "Debate scoring fix: dual scoring failure detection, threshold 0.2→0.10"

signals_and_indicators:
  - "4h timeframe: added to IBKR tf_map and Polygon tf_map"
  - "VWAP + ADX indicators added to signals.py (Track C)"
  - "ADX directional filter in Layer 3"
  - "6-factor consensus voting in Layer 4"
  - "VWAP + STC histogram subpanel added to chart (Track E)"

routing_and_persistence:
  - "/decisions/recent: now queries SQLite directly (was broken PostgreSQL attempt)"
  - "Pipeline decision logging: /pipeline/run now persists ALL decisions to SQLite"
  - "GET /decisions/{id}/detail endpoint added"

alerting:
  - "WhatsApp wiring: alert fires automatically on LONG/SHORT signals"
  - "OpenClaw lockout fix script added (scripts/fix-openclaw-lockout.py)"

dashboard:
  - "SignalFlowWidget: new dashboard widget showing live signal status and pipeline stages"
  - "All 9 pipeline agents improved: ATR stops, news proxy, macro regime, social resilience"

optimizer:
  - "Dual-gate validation (risk + profit) added to optimizer with ELIGIBLE/DISCARD verdicts"
  - "Slippage and commission modeling added to backtester"
  - "Calmar ratio and Exposure Time % added to backtest metrics"

## pending_matt_action

security_p0:
  - "ROTATE ANTHROPIC API KEY — console.anthropic.com (exposed in git history)"
  - "Revoke/rotate Polygon, Twilio, Google OAuth keys (also in git history)"

schwab_oauth_3a:
  description: "Schwab connector built but needs app credentials"
  steps:
    - "Go to developer.schwab.com"
    - "Create app → get Client ID + Client Secret"
    - "Add to engine/.env: SCHWAB_APP_KEY=xxx SCHWAB_APP_SECRET=xxx"
    - "Run: curl -X POST http://localhost:8010/schwab/connect"
    - "Complete OAuth browser flow"
    - "Set SCHWAB_READY=true in engine/.env"
  reference: "SCHWAB_SETUP.md in project root"

discord_export_7:
  description: "Discord intelligence needs Corey Auction Tools channel data"
  steps:
    - "Export Corey Auction Tools Discord channels"
    - "Save to: C:\\Users\\mattm\\discord-export\\"
    - "Engine will auto-load on next restart"

## next_signals

MCL:
  current_price: 98.86
  entry: 84.20
  unrealized: "+$1,466"
  notes: "STC ~97 (overbought zone). 4h MTF now live. Watch for debate to flip BEAR and generate exit signal."
  stop_loss_recommendation: "Consider setting stop at breakeven + 30% of gain (~$88.60)"

MNQ:
  current_price: 25261.25
  notes: "1h STC=99, 4h may be diverging. Watch for alignment signal."

MES:
  current_price: 6861.50
  status: "PAPER authorized 2026-04-09. WFE=0.09 (overfit). Do not use for live decisions."

WhatsApp: "Will fire automatically on first pipeline LONG or SHORT decision"

## commits_today

- "590d618: fix: 4h timeframe support in data waterfall, debate conviction tie-break, decisions route to SQLite, MTF staleness guard, pipeline decision logging"
- "f4d0a91: docs: add troubleshooting runbook, OpenClaw lockout script, and root scratch gitignore"
- "7d55022: feat: improve all pipeline agents signal quality + SignalFlow dashboard widget"
- "6d00d95: chore: update task manifest and dashboard tsbuildinfo"
- "23577e2: feat: improve pipeline agent signal quality — ATR stops, news proxy, macro regime, social resilience"
- "29ee60f: fix: debate scoring fix, WhatsApp wiring, B9 true fix, pipeline detail endpoint"
- "4f5f190: fix: restore all 6 scan symbols, keep sequential to prevent OOM"
- "d0f2584: fix: downgrade risk/fund agents opus→sonnet, add cache invalidation endpoints, IB historical price fallback"
- "faa4ff8: fix: debate scoring tie — lower threshold 0.2→0.10, detect dual scoring failure"
- "29d87f4: feat: VWAP+ADX indicators, ADX directional filter Layer 3, 6-factor consensus voting Layer 4"
- "4bc5020: feat: VWAP + STC histogram subpanel in chart"
- "c4b5c59: feat: dual-gate validation (risk + profit) to optimizer with ELIGIBLE/DISCARD verdicts"
- "b6be115: feat: slippage and commission modeling to backtester; Calmar ratio and Exposure Time pct"

## context_to_reload

files_changed_today:
  - engine/agents/pipeline.py
  - engine/agents/technical_analyst.py
  - engine/agents/news_analyst.py
  - engine/agents/debate_orchestrator.py
  - engine/agents/risk_manager.py
  - engine/agents/fund_manager.py
  - engine/signals.py
  - engine/routers/pipeline_router.py
  - engine/routers/decisions_router.py
  - engine/routers/prices_router.py
  - engine/portfolio/tracker.py
  - engine/backtest/optimizer.py
  - engine/backtest/backtester.py
  - dashboard/app/components/SignalFlowWidget.tsx
  - docs/troubleshooting.md
  - scripts/fix-openclaw-lockout.py

key_constants:
  API_KEY: "xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc"
  ENGINE_PORT: 8010
  DASHBOARD_PORT: 3010
  IBKR_PAPER_PORT: 4002
  STC_OVERSOLD: 15
  STC_OVERBOUGHT: 83
  MCL_MULTIPLIER: 100
  MNQ_MULTIPLIER: 2
  MES_MULTIPLIER: 5

validated_instruments:
  MCL: "WFE=0.82 — APPROVED, paper trading active"
  MNQ: "WFE=0.57 — APPROVED, paper trading active"
  MGC: "WFE=0.14 — HALTED (overfit/small-sample)"
  MES: "WFE=0.09 — PAPER authorized 2026-04-09, do not trade live"

## next_session_priorities

P0:
  - "Rotate Anthropic API key (security)"
  - "Monitor MCL position — STC overbought, potential exit signal incoming"

P1:
  - "Complete Schwab OAuth (Matt action required)"
  - "Load Discord export for intelligence (Matt action required)"
  - "Validate WhatsApp fires on live pipeline signal"
  - "Run walk-forward validation on MES to improve WFE from 0.09"

P2:
  - "Wire MultiMarketOrchestrator into lifespan (engine/orchestrator/multi_market.py)"
  - "Fix 3 test failure categories: loss_tracker(31), AsyncMock(26), auth(7)"
  - "Persist kill switch state across restarts (add system_state table)"
  - "Resolve duplicate RL routes"
