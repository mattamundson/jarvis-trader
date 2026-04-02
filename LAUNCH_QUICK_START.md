# JARVIS TRADER — Quick Start Guide (Paper Trading)

> **Launch scripts with comprehensive safety verification for paper trading mode**

---

## One-Minute Setup

### 1. Verify Prerequisites

```powershell
java -version          # JRE 11+ (for IB Gateway)
node --version         # Node.js 18+ (for PM2 and dashboard)
pm2 --version          # PM2 installed globally
type engine\.env       # .env file exists
```

### 2. Launch Paper Trading

```powershell
.\scripts\launch_paper_trading.ps1
```

That's it. The script handles:
- Dependency validation (Java, Node, PM2, Python venv)
- .env configuration checks
- Safety verification (kill switch, paper mode)
- Test suite execution
- Engine startup via PM2
- Dashboard launch
- Health checks and browser open

---

## What the Launch Script Does

```
PHASE 1: Preflight Checks         [Java, Node, PM2, Python venv]
PHASE 2: .env Validation          [Required vars, no placeholders]
PHASE 3: Infrastructure           [Docker, Postgres, Redis, IB Gateway]
PHASE 4: Safety Verification      [config.py, safety_layer.py, kill switch]
PHASE 5: Test Suite               [pytest tests/test_safety_layer.py]
PHASE 6: Launch Sequence          [PM2 start, health check, dashboard]
PHASE 7: Post-Launch Verification [/health, /safety/status, /portfolio]
```

**Aborts immediately on ANY safety check failure.**

---

## Access Points

| Service | URL |
|---------|-----|
| **Dashboard** | http://localhost:3010 |
| **Engine** | http://localhost:8010 |
| **API Docs** | http://localhost:8010/docs |
| **Health** | http://localhost:8010/health |
| **Safety Status** | http://localhost:8010/safety/status |
| **Portfolio** | http://localhost:8010/portfolio |

---

## Stopping Paper Trading

```powershell
.\scripts\stop_paper_trading.ps1
```

Cleanly shuts down:
- All PM2 processes (engine, rolling WFE)
- Background dashboard process
- Provides shutdown status and logs

---

## Safety Guarantees

The launch scripts enforce non-negotiable safety rules:

✓ **LIVE_TRADING_ENABLED = False** (hardcoded in code)
✓ **PAPER_TRADING = True** (validated in .env)
✓ **REQUIRE_HUMAN_APPROVAL = True** (every trade requires approval)
✓ **Kill Switch** = -2% daily loss OR -10% drawdown (triggers immediate halt)
✓ **Safety Tests Pass** (aborts if test_safety_layer.py fails)

---

## Common Issues

### "Engine health check failed after 30 attempts"

**Fix:**
```powershell
# Check engine logs
type engine\logs\engine-out.log

# Verify venv
engine\.venv\Scripts\pip list | findstr fastapi

# Check .env is loaded
type engine\.env | findstr ANTHROPIC_API_KEY

# Or start manually
cd engine
.\.venv\Scripts\python -m uvicorn main:app --port 8010
```

### "Safety layer tests failed"

**Fix:** Don't skip tests. They are non-negotiable. Review test output:
```powershell
cd engine
.\.venv\Scripts\python -m pytest tests\test_safety_layer.py -v
```

### "IB Gateway not reachable"

**Fix:** Start IB Gateway first
```powershell
# Or skip check for now
.\scripts\launch_paper_trading.ps1 -SkipIBCheck
```

### "PM2 failed to start"

**Fix:**
```powershell
pm2 --version                    # Verify PM2 installed
pm2 validate                     # Check ecosystem.config.js
pm2 logs jarvis-engine           # View engine logs
```

---

## Environment Variables (.env)

**Critical variables (must be set):**

```bash
PAPER_TRADING=True                    # REQUIRED — must be True
LIVE_TRADING_ENABLED=False            # REQUIRED — must be False
ANTHROPIC_API_KEY=sk-ant-...          # API key (sk-ant- prefix)
POSTGRES_URL=postgresql://...         # DB connection
IBKR_PORT=4002                        # IB Gateway port (paper trading)
```

**Copy from example:**
```powershell
Copy-Item engine\.env.example engine\.env
# Edit engine\.env with real values
```

---

## Development Options

```powershell
# Skip test suite (dev only — not recommended)
.\scripts\launch_paper_trading.ps1 -SkipTests

# Skip IB Gateway check (if not ready)
.\scripts\launch_paper_trading.ps1 -SkipIBCheck

# Combine both
.\scripts\launch_paper_trading.ps1 -SkipTests -SkipIBCheck
```

---

## Monitoring

### Engine Logs

```powershell
# Real-time logs
pm2 logs jarvis-engine

# Full log file
type engine\logs\engine-out.log

# Error logs
type engine\logs\engine-error.log
```

### Dashboard

```powershell
# Real-time logs (in dashboard terminal)
pnpm dev
```

### Health Status

```powershell
# Manual health check
curl http://localhost:8010/health

# Safety status
curl http://localhost:8010/safety/status

# Portfolio status
curl http://localhost:8010/portfolio
```

---

## Kill Switch Status

Check if trading is halted:

```powershell
curl http://localhost:8010/safety/status
```

Response shows:
- `kill_switch_active`: true/false
- `paper_mode`: true/false
- `daily_pnl_pct`: current daily P&L
- `drawdown_pct`: current drawdown

**Kill switch triggers automatically at:**
- **-2% daily loss** (daily P&L halt)
- **-10% drawdown** (emergency halt)

---

## Validated Instruments

| Symbol | Status | Notes |
|--------|--------|-------|
| MCL | APPROVED | Paper trading active |
| MNQ | APPROVED | Paper trading active |
| MGC | HALTED | Overfit/small-sample |
| MES | DO NOT TRADE | Low validation efficiency |

---

## Documentation

| Document | Path |
|----------|------|
| Launch script reference | `scripts/README_LAUNCH.md` |
| Project overview | `CLAUDE.md` |
| Safety rules | `.claude/rules/safety.md` |
| Testing rules | `.claude/rules/testing.md` |
| Paper trading runbook | `docs/runbooks/PAPER_TRADING.md` |
| PM2 config | `engine/ecosystem.config.js` |

---

## Next Steps

1. Configure `.env` with API keys and database URLs
2. Start Docker compose: `docker-compose up -d`
3. Launch paper trading: `.\scripts\launch_paper_trading.ps1`
4. Open dashboard: http://localhost:3010
5. Monitor logs: `pm2 logs jarvis-engine`
6. Review safety status: `curl http://localhost:8010/safety/status`

---

## Safety Reminder

**DO NOT modify safety parameters without explicit Tier 3 authorization.**

The launch scripts enforce hardcoded safety rules that cannot be bypassed:
- Kill switch thresholds are non-negotiable
- Live trading is permanently disabled in code
- Human approval is required for every trade
- Safety layer tests must pass before launch

**Paper trading must remain safely contained before moving to live capital.**

---

For detailed documentation, see `scripts/README_LAUNCH.md`
