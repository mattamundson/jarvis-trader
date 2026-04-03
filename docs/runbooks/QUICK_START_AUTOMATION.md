# Quick Start — Daily Automation Scripts

> Get health checks, morning briefs, and EOD summaries running in 5 minutes.

---

## TL;DR

```bash
# Terminal 1: Start engine (if not already running)
cd engine
.venv\Scripts\python -m uvicorn main:app --port 8010

# Terminal 2: Start PM2 automation (one-time setup)
cd engine
pm2 start ecosystem.config.js
pm2 save
pm2 startup

# Done! Scripts run automatically at scheduled times.
```

---

## Manual Runs (for testing)

```bash
cd engine

# Health check (now)
.venv\Scripts\python scripts/daily_health_check.py

# Morning brief (now)
.venv\Scripts\python scripts/morning_brief.py

# EOD summary (now)
.venv\Scripts\python scripts/eod_summary.py
```

---

## Monitor Scheduled Jobs

```bash
# See all PM2 processes
pm2 status

# Watch logs in real-time
pm2 logs jarvis-morning-brief
pm2 logs jarvis-eod-summary
pm2 logs jarvis-health-check

# Stop all
pm2 stop all

# Restart all
pm2 restart all

# View detailed process info
pm2 show jarvis-morning-brief
```

---

## What Gets Generated?

| Script | Output File | When | Content |
|--------|-------------|------|---------|
| **daily_health_check.py** | `data/daily_health_log.json` | Every 30 min (8am–5pm CT) | Engine status, equity, P&L, positions |
| **morning_brief.py** | `data/morning_briefs/YYYY-MM-DD.md` | 6:30am CT daily | VIX, prices, sentiment, portfolio |
| **eod_summary.py** | `data/daily_journals/YYYY-MM-DD.md` | 4:05pm CT daily | Trades, P&L, learning insights |

Check outputs:
```bash
# View today's files
cat engine/data/morning_briefs/2026-04-02.md
cat engine/data/daily_journals/2026-04-02.md
cat engine/data/daily_health_log.json | tail -1
```

---

## Troubleshooting

**Scripts not running?**
```bash
pm2 status                  # Check if processes exist
pm2 logs jarvis-morning-brief --err  # Check for errors
pm2 restart jarvis-engine   # Restart engine
```

**Engine offline error?**
```bash
pm2 logs jarvis-engine      # Check engine logs
pm2 restart jarvis-engine   # Restart engine
# OR manually in another terminal:
cd engine && .venv\Scripts\python -m uvicorn main:app --port 8010
```

**Wrong file output location?**
- Check `engine/data/morning_briefs/` and `engine/data/daily_journals/` exist
- If missing: `mkdir -p engine/data/{morning_briefs,daily_journals}`

**Cron schedule not working?**
- Verify machine time is correct
- Check PM2 cron timezone: `pm2 logs` should show when jobs run
- Manually trigger a test: `.venv\Scripts\python scripts/morning_brief.py`

---

## File Locations

```
engine/
├── scripts/
│   ├── daily_health_check.py
│   ├── morning_brief.py
│   └── eod_summary.py
├── data/
│   ├── daily_health_log.json
│   ├── morning_briefs/
│   │   └── 2026-04-02.md
│   └── daily_journals/
│       └── 2026-04-02.md
└── logs/
    ├── health_check.log
    ├── morning_brief.log
    └── eod_summary.log
```

---

## Next Steps

1. Verify scripts work: Manual test each one ✓
2. Enable PM2 automation: `pm2 start ecosystem.config.js` ✓
3. Persist on reboot: `pm2 save && pm2 startup` ✓
4. Monitor daily: Check `pm2 logs` and file outputs ✓

See `DAILY_AUTOMATION.md` for full documentation.
