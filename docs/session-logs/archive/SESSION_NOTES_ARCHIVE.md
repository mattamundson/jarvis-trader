# JARVIS TRADER — Session Notes

> Auto-generated session archive. Last updated: 2026-03-28

---

## Project Overview

**JARVIS TRADER** — AI-powered autonomous trading system for futures and options.
- **Engine** (Python/FastAPI): `engine/` — port 8010
- **Dashboard** (Next.js): `dashboard/` — port 3010
- **Git initialized**: Yes (commit `1c256a0` — "Initial scaffold: JARVIS TRADER v0.1")

**User context**: Matt trades futures + options in ThinkorSwim. Will open IBKR account later for automated execution.

---

## Architecture Summary (49 files, ~7,684 lines)

### Engine Structure
```
engine/
├── main.py              # FastAPI server, port 8010
├── config.py            # Settings from .env
├── .env                 # Configured (Anthropic API key set)
├── agents/
│   ├── technical_analyst.py    # pandas-ta indicators + LLM
│   ├── news_analyst.py         # Finnhub headlines + claude-sonnet-4-6
│   ├── social_analyst.py       # ApeWisdom + StockTwits + claude-haiku-4-5
│   ├── fundamental_analyst.py  # FRED economic data + Finnhub metrics
│   ├── bull_researcher.py      # Optimistic case builder
│   ├── bear_researcher.py      # Risk/downside case builder
│   ├── debate_orchestrator.py  # Bull/Bear synthesis
│   ├── trader.py               # Trade decision (claude-opus-4-6)
│   ├── risk_manager.py         # 2-layer: Python hard rules + LLM
│   ├── fund_manager.py         # Portfolio-level approval gate
│   ├── pipeline.py             # 5-stage orchestrator
│   └── __init__.py
├── data/
│   ├── market_data.py          # MarketDataManager (IBKR + Polygon + yfinance)
│   └── reddit.py               # ApeWisdom scraper
├── execution/
│   ├── ibkr_executor.py        # IBKR via ib_async (659 lines)
│   ├── schwab_connector.py     # Schwab via schwab-py
│   ├── order_router.py         # Smart broker routing
│   └── __init__.py
├── risk/
│   └── safety_layer.py         # Kill switch, daily loss, drawdown limits
└── requirements.txt            # Full deps (includes heavy ones)
```

### Dashboard Structure
```
dashboard/          # Next.js 14 App Router, dark terminal aesthetic
├── app/
│   ├── page.tsx    # Main dashboard (SWR polling, 5s refresh)
│   └── layout.tsx
├── components/
│   ├── KillSwitch.tsx       # Emergency stop button
│   ├── PositionsPanel.tsx   # Open positions
│   ├── AgentFeed.tsx        # Decision log feed
│   ├── SentimentPanel.tsx   # Reddit/news sentiment
│   ├── PerformancePanel.tsx # Equity curve + metrics
│   ├── WatchlistBar.tsx     # Ticker bar
│   └── ui/                  # shadcn components (badge, card, button)
├── lib/
│   ├── api.ts      # fetchEngine() + type definitions
│   └── utils.ts    # formatCurrency, formatPercent, cn()
└── package.json    # Next.js 14, Tailwind, recharts, lucide, swr
```

---

## Pipeline Flow (5 Stages)

```
Stage 1 — Analysis (parallel asyncio.gather):
  TechnicalAnalyst + NewsAnalyst + SocialAnalyst + FundamentalAnalyst

Stage 2 — Debate:
  BullResearcher.argue() || BearResearcher.argue() → DebateOrchestrator.synthesize()

Stage 3 — Trade Decision:
  TraderAgent.decide(debate_result, all_analyst_reports)
  → TradeDecision{action, quantity, order_type, signal_score, confidence}

Stage 4 — Risk Review (2-layer):
  Layer 1: Python hard rules (kill switch, daily loss, drawdown >9%, order value)
  Layer 2: LLM soft review (claude-opus-4-6)
  → RiskDecision{approved, veto_reason, modified_quantity, risk_score}

Stage 5 — Fund Manager Approval:
  FundManagerAgent.approve(risk_decision, trade_decision, portfolio)
  → FundDecision{approved, priority, requires_human_approval}
  → requires_human_approval=True if REQUIRE_HUMAN_APPROVAL env var OR trade > $2,000
```

---

## Configuration (.env)

| Variable | Value |
|----------|-------|
| `IBKR_PORT` | 4002 (paper trading) |
| `IBKR_PAPER_MODE` | True |
| `ANTHROPIC_API_KEY` | ✅ Configured (from GMS JARVIS) |
| `LIVE_TRADING_ENABLED` | False |
| `REQUIRE_HUMAN_APPROVAL` | True |
| `POSTGRES_URL` | postgresql://jarvis:jarvis@localhost:5432/jarvis_trader |
| `REDIS_URL` | redis://localhost:6379 |
| Schwab/Polygon/Finnhub/Alpaca | Placeholders — fill in when ready |

---

## API Endpoints (engine/main.py)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System status, broker connections |
| POST | `/safety/kill-switch/activate` | Emergency stop |
| POST | `/safety/kill-switch/deactivate` | Resume trading |
| GET | `/safety/status` | Risk metrics, daily P&L |
| POST | `/analyze/technical` | Run TechnicalAnalystAgent |
| GET | `/analyze/bars/{symbol}` | OHLCV bars |
| GET | `/sentiment/reddit` | Trending Reddit tickers |
| GET | `/sentiment/news/{symbol}` | Finnhub news sentiment |
| GET | `/portfolio` | Current positions + equity |
| GET | `/decisions/recent` | Agent decision log |
| POST | `/decisions/log` | Log a decision (internal) |
| GET | `/sentiment/recent` | Latest sentiment scores |
| GET | `/watchlist` | Configured watchlists |
| POST | `/pipeline/run` | Run full 5-stage analysis pipeline on a symbol |
| GET | `/pipeline/status` | Current pipeline run status |
| GET | `/prices/snapshot` | Live prices for watchlist symbols (yfinance) |
| POST | `/thinkscript/generate` | Generate ThinkorSwim script via LLM |
| POST | `/notifications/telegram/test` | Send test Telegram alert |
| GET | `/scheduler/status` | APScheduler job status |

---

## Session 1 Work (2026-03-28)

### Completed
- [x] Full project scaffold built (49 files by parallel agents)
- [x] Git initialized + initial commit (`1c256a0`)
- [x] `.env` created from `.env.example`
- [x] Anthropic API key injected into `.env`
- [x] Plan approved: get running locally + wire pipeline

### COMPLETED THIS SESSION
- [x] Python venv created with Python 3.12 (3.14 breaks numpy)
- [x] requirements-core.txt created (removed ta-lib, vectorbt, nautilus_trader, langchain)
- [x] All 60+ Python packages installed successfully
- [x] Fixed pandas-ta version (0.3.14b→0.4.67b0), numpy (>=2.2.6), relaxed version pins
- [x] Fixed pandas_ta Windows bug: `from posix import pread` in alligator.py (Linux-only)
- [x] Fixed ib_async import → try/except guard in ibkr_executor.py
- [x] Fixed schwab import path `engine.risk.` → `risk.` in schwab_connector.py
- [x] Fixed TradingPipeline() instantiation (was missing required args)
- [x] Polygon API fallback to yfinance when API key is placeholder
- [x] POST /pipeline/run + GET /pipeline/status endpoints
- [x] GET /prices/snapshot endpoint (yfinance live prices)
- [x] Updated /watchlist endpoint with live yfinance prices
- [x] POST /thinkscript/generate endpoint
- [x] POST /notifications/telegram/test endpoint
- [x] GET /scheduler/status endpoint
- [x] ThinkScriptGeneratorAgent created (engine/agents/thinkscript_generator.py)
- [x] TelegramNotifier created (engine/notifications/telegram.py)
- [x] APScheduler watchlist scan every 30min on weekdays 9:30am-4pm CT
- [x] npm install dashboard (465 packages, Next.js 15.3)
- [x] Badge component verified (pure Tailwind, no missing Radix dep)
- [x] SWR type inference fixed (0 TypeScript errors)
- [x] "Run Analysis" button added to dashboard homepage
- [x] /analysis page created (full pipeline results with expandable stage cards)
- [x] fetchEngine() updated to support POST requests
- [x] Engine starts cleanly — uvicorn main:app --port 8010 ✅

### REMAINING
- [ ] Configure Telegram: add BOT_TOKEN + CHAT_ID to .env (manual — need BotFather)
- [ ] Test /pipeline/run end-to-end (requires running engine + Anthropic API call)
- [ ] Open IBKR account for futures execution
- [ ] 3+ months paper trading before live

### QUICK START
```bash
# Terminal 1: Engine
cd C:/Users/mattm/OneDrive/Documents/ThinkorSwim/jarvis-trader/engine
.venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Terminal 2: Dashboard
cd C:/Users/mattm/OneDrive/Documents/ThinkorSwim/jarvis-trader/dashboard
npm run dev
```

Then visit:
- Dashboard: http://localhost:3010
- Analysis page: http://localhost:3010/analysis
- API docs: http://localhost:8010/docs

---

## Key Technical Notes

### Safety Architecture
- Kill switch activates automatically on: daily loss breach, max drawdown 10%, manual activation
- Non-LLM hard rules run FIRST before any LLM agent
- `REQUIRE_HUMAN_APPROVAL=True` means all trades require dashboard confirmation
- Paper mode active: `LIVE_TRADING_ENABLED=False`

### LLM Models Used
| Agent | Model | Why |
|-------|-------|-----|
| TechnicalAnalyst | claude-opus-4-6 | Complex multi-indicator synthesis |
| NewsAnalyst | claude-sonnet-4-6 | Good enough for headline analysis |
| SocialAnalyst | claude-haiku-4-5 | Lightweight, high frequency |
| FundamentalAnalyst | claude-sonnet-4-6 | Macro + metrics analysis |
| Bull/Bear Researcher | claude-sonnet-4-6 | Research quality needed |
| DebateOrchestrator | claude-opus-4-6 | Most important synthesis step |
| Trader | claude-opus-4-6 | High-stakes decision |
| RiskManager | claude-opus-4-6 | Risk assessment critical |
| FundManager | claude-opus-4-6 | Final approval gate |

### Data Sources (free tier)
- **yfinance**: Historical OHLCV, free, no key needed
- **Finnhub**: News + sentiment, free tier (60 req/min)
- **ApeWisdom**: Reddit trending, no API key
- **StockTwits**: Social sentiment, no API key
- **FRED**: Economic data (Fed Funds, 10Y, VIX), no API key
- **Alpaca**: Paper trading data, free with API key

### Watchlists (default)
- Futures: MES, MNQ, MCL
- Options: SPY, QQQ, AAPL, TSLA, NVDA

---

## Quick Start Commands

```bash
# Terminal 1: Engine
cd C:/Users/mattm/OneDrive/Documents/ThinkorSwim/jarvis-trader/engine
.venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Terminal 2: Dashboard
cd C:/Users/mattm/OneDrive/Documents/ThinkorSwim/jarvis-trader/dashboard
npm run dev

# Test health
curl http://localhost:8010/health

# Run analysis
curl -X POST http://localhost:8010/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SPY", "is_futures": false}'
```

Visit:
- Dashboard: http://localhost:3010
- Analysis page: http://localhost:3010/analysis
- API docs: http://localhost:8010/docs

---

## File Locations
- **Project root**: `C:\Users\mattm\OneDrive\Documents\ThinkorSwim\jarvis-trader\`
- **Engine**: `engine/`
- **Dashboard**: `dashboard/`
- **Plan**: `C:\Users\mattm\.claude\plans\whimsical-swinging-dongarra.md`
