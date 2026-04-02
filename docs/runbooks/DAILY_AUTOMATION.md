# JARVIS TRADER — Daily Operations Automation

> Standalone scripts for paper trading phase. Automate health checks, pre-market briefs, and end-of-day summaries.

**Status**: Production-ready (as of 2026-04-02)
**Engine Version**: 0.1.0 | **Python**: 3.12 | **venv**: engine/.venv/

---

## Overview

Three automation scripts run on configurable schedules during the trading day:

| Script | Purpose | Schedule | Output |
|--------|---------|----------|--------|
| `daily_health_check.py` | Engine health + safety validation | Every 30 min (8am–5pm CT) | `data/daily_health_log.json` |
| `morning_brief.py` | Pre-market intelligence snapshot | 6:30am CT weekdays | `data/morning_briefs/YYYY-MM-DD.md` |
| `eod_summary.py` | Daily journal + learning insights | 4:05pm CT weekdays | `data/daily_journals/YYYY-MM-DD.md` |

All scripts:
- Use `httpx` or stdlib `urllib` for HTTP calls to `http://localhost:8010`
- Handle graceful failures (engine down, endpoint unavailable)
- Log to file + console
- Exit code 0 for success, 1 for issues
- Are ruff-clean and Pydantic v2 compliant

---

## Installation & Setup

### Prerequisites

```bash
cd engine
python -m venv .venv                                    # If not already created
.venv\Scripts\pip install -r requirements-core.txt     # Install dependencies
```

### Manual Testing

```bash
# Health check
.venv\Scripts\python scripts/daily_health_check.py

# Morning brief
.venv\Scripts\python scripts/morning_brief.py

# EOD summary
.venv\Scripts\python scripts/eod_summary.py
```

### Automated Scheduling (PM2)

1. Install PM2 globally:
   ```bash
   npm install -g pm2
   ```

2. Start all processes:
   ```bash
   pm2 start ecosystem.config.js
   ```

3. Verify processes are running:
   ```bash
   pm2 status
   pm2 logs jarvis-morning-brief
   pm2 logs jarvis-eod-summary
   pm2 logs jarvis-health-check
   ```

4. Persist on reboot:
   ```bash
   pm2 save
   pm2 startup
   ```

---

## Scripts in Detail

### 1. Daily Health Check (`scripts/daily_health_check.py`)

**Purpose**: Validates engine operational status and trading readiness every 30 minutes.

**Schedule (PM2)**: `*/30 8-16 * * 1-5` — every 30 minutes, 8:00am–4:59pm CT, weekdays only

**API Calls**:
```
GET /health                        Engine status & uptime
GET /safety/status                 Kill switch, P&L, drawdown, order rate
GET /portfolio                     Equity, cash, positions
GET /paper/validation/progress     30-day validation metrics (optional)
```

**Outputs**:
1. **Console**: One-line summary (e.g., "Day 5/30 | Equity: $10,045.50 | P&L: +$45.50 | Trades: 2 | ON_TRACK")
2. **Log File**: `logs/health_check.log` with timestamps
3. **JSON Log**: `data/daily_health_log.json` — appended array of check entries

**Example Entry** (`daily_health_log.json`):
```json
{
  "timestamp": "2026-04-02T10:30:00-05:00",
  "status": "HEALTHY",
  "summary": "Day 5/30 | Equity: $10,045.50 | P&L: +$45.50 | Trades: 2 | ON_TRACK",
  "issues": [],
  "engine_online": true,
  "kill_switch_active": false,
  "daily_pnl": 45.50,
  "drawdown_pct": -0.015,
  "equity": 10045.50,
  "open_positions": 1,
  "validation": "Day 5/30 | 5d running | 2 trades | Target: 30"
}
```

**Exit Codes**:
- `0`: Engine healthy, all checks pass
- `1`: Engine down OR safety limits breached

**Failure Handling**:
- Engine offline: Logs error, returns exit code 1, continues next cycle
- /safety/status unavailable: Warns, marks `is_healthy = false`
- /portfolio unavailable: Warns, marks `is_healthy = false`

---

### 2. Morning Brief (`scripts/morning_brief.py`)

**Purpose**: Pre-market intelligence brief delivered 2 hours before RTH open.

**Schedule (PM2)**: `30 6 * * 1-5` — 6:30am CT, weekdays only

**API Calls**:
```
GET /health                        Engine status
GET /macro/snapshot                VIX, yields, DXY, macro regime, events
GET /prices/snapshot               Overnight price changes (MES, MNQ, MCL, SPY, QQQ)
GET /sentiment/recent              Reddit sentiment on watchlist
GET /portfolio                     Equity, cash, positions
GET /decisions/recent?limit=5      Recent pipeline decisions (non-HOLD)
GET /scheduler/status              Scheduler running state, next scan
```

**Output**:
1. **Console**: Formatted ASCII brief with tables and sections
2. **File**: `data/morning_briefs/YYYY-MM-DD.md` — Markdown formatted brief

**Example Brief Structure**:
```markdown
======================================================================
JARVIS TRADER — Pre-Market Brief | Thursday, April 02, 2026 | 6:30am CT
======================================================================

SYSTEM STATUS
  Status:  ONLINE
  Uptime:  72h 15m

MACRO SNAPSHOT
  VIX:       15.50 (LOW)
  10yr Yld:  4.215%
  DXY:       104.5
  Regime:    RISK_ON
  Notes:     Fed decision Wednesday — monitor closely
  Events:
    - CPI 8:30am ET
    - Existing Homes Sales 10:00am ET

MARKET SNAPSHOT
Symbol       Price     Prev Close   % Change
-------------------------------------------
MES         5510.50      5505.00      +0.10%
MNQ        19350.00     19320.00      +0.15%
...

OVERNIGHT SENTIMENT (Reddit)
     SPY: BULLISH (score: +0.35, 4521 posts)
     QQQ:  NEUTRAL (score: -0.05, 3210 posts)

PORTFOLIO
  Equity:       $10,045.50
  Daily P&L:    +$45.50 (+0.45%)
  Positions:    1 open

RECENT DECISIONS (non-HOLD)
  1. MES BUY | Confidence: 0.72
     MES | regime=trending_up trend=bullish | action=BUY qty=1 | conviction=72%

SCHEDULER
  Status:               RUNNING
  Next scan:            2026-04-02T08:00:00-05:00
  Total decisions:      12

======================================================================
Matt's Schedule Today
  8:00–8:30am CT:  Active prep window (Matt)
  8:30–9:35am CT:  Avoid noise (high volatility)
  9:35–11:30am CT: Primary trading window (LIVE)
  1:00–3:30pm CT:  Secondary trading window (LIVE)
======================================================================
```

**Failure Handling**:
- Engine offline: Aborts brief, outputs error message only
- FRED API not configured: Skips macro section with note
- Sentiment unavailable: Skips sentiment section
- Prices unavailable: Shows "N/A" for symbols

---

### 3. End-of-Day Summary (`scripts/eod_summary.py`)

**Purpose**: Daily journal entry with trades, P&L, and learning system insights.

**Schedule (PM2)**: `5 16 * * 1-5` — 4:05pm CT, weekdays only

**API Calls**:
```
GET /portfolio                     Final equity, positions, P&L
GET /safety/status                 Final daily P&L %, drawdown
GET /decisions/recent?limit=20     All decisions (filters to trades only)
GET /paper/validation/progress     30-day validation metrics
GET /learning/patterns             Learning system insights (optional)
```

**Output**:
1. **Console**: Formatted ASCII journal entry
2. **File**: `data/daily_journals/YYYY-MM-DD.md` — Markdown journal

**Example Journal Entry**:
```markdown
======================================================================
JARVIS TRADER — Daily Journal | Thursday, April 02, 2026 | 4:05pm CT
======================================================================

PORTFOLIO EOD
  Total Equity:     $10,045.50
  Cash Balance:     $9,045.50
  Realized P&L:     +$45.50
  Unrealized P&L:   +$0.00
  Daily P&L:        +$45.50 (+0.45%)
  Open Positions:   1
    - MES: +1 @ 5510.50 (current: 5510.50, U/L: +$0.00)

RISK METRICS EOD
  Kill Switch:      OFF
  Daily P&L %:      +0.45% (limit: -2.0%)
  Drawdown:         -0.50% (limit: -10.0%)

TRADES TAKEN TODAY (2 trades)
  1. MES BUY | Confidence: 0.72
     MES | regime=trending_up trend=bullish | action=BUY qty=1 | conviction=72%
  2. MES SELL | Confidence: 0.55
     MES | regime=ranging trend=neutral | action=SELL qty=1 | conviction=55%

30-DAY VALIDATION PROGRESS
  Current Day:      Day 5/30
  Running Days:     5
  Total Trades:     8 (target: 30)
  Trades Today:     2

LEARNING SYSTEM — PATTERNS DETECTED
  - STC Oversold Bounce (confidence: 0.89)
  - Morning Gap Reversion (confidence: 0.76)

LEARNING SYSTEM — RECOMMENDATIONS
  - Increase MES allocation on oversold bounces: Strong edge detected
  - Reduce size on high-VIX setups: Increased risk/reward ratio deteriorates
  - Monitor gap reversions for entry bias: Directional lean consistent

======================================================================
END OF DAY NOTES
  Reflect on today's trades, setups, and execution.
  Use learning system insights for tomorrow's plan.
======================================================================
```

**Failure Handling**:
- Portfolio unavailable: Aborts journal, outputs error message
- Safety status unavailable: Continues with warning
- Decisions unavailable: Skips "TRADES TAKEN" section
- Learning system unavailable: Skips patterns/recommendations section

---

## Data Storage

### Directories Created Automatically

```
engine/
├── data/
│   ├── daily_health_log.json          # Appended array of health checks
│   ├── morning_briefs/
│   │   ├── 2026-04-02.md
│   │   ├── 2026-04-03.md
│   │   └── ...
│   └── daily_journals/
│       ├── 2026-04-02.md
│       ├── 2026-04-03.md
│       └── ...
└── logs/
    ├── health_check.log
    ├── health_check-error.log
    ├── morning_brief.log
    ├── morning_brief-error.log
    ├── eod_summary.log
    └── eod_summary-error.log
```

### Log Retention

- **Console logs**: Stored in PM2 log files (rotated by PM2)
- **Script logs**: Keep indefinitely in `logs/` (manually prune if needed)
- **Data files**: Keep indefinitely (CSV/JSON, minimal storage)

---

## Monitoring & Troubleshooting

### Check Script Status

```bash
# List all processes
pm2 status

# Watch real-time logs
pm2 logs jarvis-health-check
pm2 logs jarvis-morning-brief
pm2 logs jarvis-eod-summary

# Check for errors
pm2 logs jarvis-health-check --err
pm2 logs jarvis-morning-brief --err

# View process details
pm2 info jarvis-health-check
```

### Common Issues

**1. "Engine is OFFLINE" in health check**
- Verify FastAPI engine is running: `pm2 status | grep jarvis-engine`
- Check engine logs: `pm2 logs jarvis-engine`
- Restart engine: `pm2 restart jarvis-engine`

**2. "FRED API not configured" in morning brief**
- Add `FRED_API_KEY` to `engine/.env`
- Restart engine: `pm2 restart jarvis-engine`

**3. Scripts not running on schedule**
- Verify PM2 is running: `pm2 status`
- Check cron timezone matches system: `pm2 logs jarvis-morning-brief`
- Restart PM2: `pm2 restart all`
- Save PM2 state: `pm2 save && pm2 startup`

**4. "Daily P&L limit breached" or "Drawdown limit hit"**
- Kill switch is active — check `/safety/status` endpoint
- Review risk parameters in `engine/config.py`
- See `.claude/rules/safety.md` for halt conditions

---

## Integration with Ecosystem

### How Scripts Interact

```
8:00am   Engine starts
         ↓
6:30am   Morning Brief runs → saves to morning_briefs/
         (next day, premarket prep)
         ↓
8:30am   RTH open
         Health Check runs (every 30 min during hours)
         ↓
4:05pm   EOD Summary runs → saves to daily_journals/
         ↓
4:00pm   RTH close
         (end of trading day)
```

### Dashboard Integration

Scripts are **independent** — they don't feed back to the dashboard automatically. To integrate:

1. **Morning Brief**: Have dashboard fetch latest from `morning_briefs/` directory
2. **Health Check**: Query `daily_health_log.json` for intraday status
3. **EOD Summary**: Link to today's journal in dashboard sidebar

Example dashboard fetch:
```typescript
// dashboard/lib/api.ts
export async function getLatestMorningBrief(): Promise<string | null> {
  const today = new Date().toISOString().split('T')[0];
  const res = await fetchEngine(`/data/morning_briefs/${today}.md`);
  return res ? res.text() : null;
}
```

---

## Safety & Compliance

**Kill Switch Integration**:
- Health check monitors `/safety/status` every 30 minutes
- If `kill_switch_active: true`, health check returns exit code 1
- Does NOT automatically disable PM2 — alert sent, manual intervention required
- See `.claude/rules/safety.md` for non-negotiable rules

**Data Privacy**:
- No API keys, credentials, or passwords in data files
- All HTTP calls use `localhost:8010` only (no external calls)
- Logs are local to engine directory (not sent anywhere)

**Paper Trading Only**:
- `LIVE_TRADING_ENABLED = False` hardcoded in `engine/config.py`
- Scripts do not interact with live brokers (IBKR, Schwab)
- All data is read-only (GET requests only)

---

## Development & Customization

### Adding a New Script

1. Create `scripts/my_script.py`
2. Follow template: async HTTP calls with graceful fallback
3. Log to `logs/` directory
4. Add PM2 entry to `ecosystem.config.js` (cron_restart schedule)
5. Test manually: `.venv\Scripts\python scripts/my_script.py`
6. Deploy: `pm2 start ecosystem.config.js --only my-process`

### Modifying Existing Scripts

- Edit script in `scripts/`
- Verify with: `python -m py_compile scripts/daily_health_check.py`
- Restart process: `pm2 restart jarvis-health-check`
- Monitor logs: `pm2 logs jarvis-health-check --lines 50`

### HTTP Request Standards

All scripts use this pattern for robustness:

```python
def _make_request(endpoint: str) -> dict | None:
    """Return JSON or None on failure (graceful fallback)."""
    url = f"{ENGINE_URL}{endpoint}"
    try:
        # httpx preferred, urllib fallback
        # timeout=10, log errors, don't crash
    except Exception:
        logger.warning(f"{endpoint}: failed")
        return None
```

---

## Scheduling Reference

### Cron Format (PM2 cron_restart)

```
minute  hour  day-of-month  month  day-of-week
  0-59  0-23      1-31     1-12      0-6 (Sun=0, Mon=1, Fri=5, Sat=6)

Examples:
30 6 * * 1-5      = 6:30am, Mon–Fri
5 16 * * 1-5      = 4:05pm, Mon–Fri
*/30 8-16 * * 1-5 = Every 30min, 8am–4:59pm, Mon–Fri
0 6 * * 1         = 6:00am Mondays only
```

### Active PM2 Jobs (ecosystem.config.js)

| Job | Cron | Purpose |
|-----|------|---------|
| jarvis-morning-brief | `30 6 * * 1-5` | 6:30am CT daily pre-market brief |
| jarvis-health-check | `*/30 8-16 * * 1-5` | Every 30min, 8am–5pm CT weekdays |
| jarvis-eod-summary | `5 16 * * 1-5` | 4:05pm CT daily EOD journal |
| jarvis-rolling-wfe | `0 6 * * 1` | Monday 6:00am — WFE recalc |

---

## Checklist for Deployment

- [ ] Python venv created: `engine/.venv/`
- [ ] Dependencies installed: `pip install -r requirements-core.txt`
- [ ] Scripts compile: `python -m py_compile scripts/*.py`
- [ ] Directories created: `data/morning_briefs/`, `data/daily_journals/`
- [ ] PM2 installed: `npm install -g pm2`
- [ ] ecosystem.config.js updated with new processes
- [ ] PM2 started: `pm2 start ecosystem.config.js`
- [ ] Processes verified: `pm2 status`
- [ ] PM2 state saved: `pm2 save && pm2 startup`
- [ ] Manual test passed: `.venv\Scripts\python scripts/daily_health_check.py` returns 0
- [ ] Logs monitored: `pm2 logs jarvis-morning-brief` shows no errors

---

## See Also

- `DAILY_ROUTINE.md` — Detailed trading operations (manual + automated)
- `engine/eod_scheduler.py` — Existing scheduler (WhatsApp integration)
- `engine/health_monitor.py` — Existing health monitor (different from these scripts)
- `.claude/rules/safety.md` — Safety invariants (kill switch, limits)
