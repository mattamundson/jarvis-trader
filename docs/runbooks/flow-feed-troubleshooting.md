# Live Order Flow Feed - Troubleshooting Runbook

## Quick Status Check

```bash
# Check health endpoint
curl https://jarvis-trader-dashboard.vercel.app/api/flow/health

# Check Windows pusher process
tasklist | findstr pythonw

# Check watchdog logs
cat $env:USERPROFILE\tape\logs\watchdog.log | tail -20

# Check pusher logs  
cat $env:USERPROFILE\tape\logs\push_flow.log | tail -50
```

---

## Problem: "STALE DATA" Badge on Dashboard

**What it means:** Data is >60 seconds old but dashboard is receiving updates.

**Root causes:**
1. Pusher script crashed
2. ThinkorSwim connection issue
3. Network connectivity problem
4. Blob storage issue

**Diagnosis:**

```bash
# 1. Is the pusher running?
tasklist | findstr pythonw
# Expected: One or more pythonw.exe processes

# 2. Check pusher logs for errors
cat $env:USERPROFILE\tape\logs\push_flow.log | tail -50
# Look for: HTTP errors, connection failures, exceptions

# 3. Check health endpoint age
curl https://jarvis-trader-dashboard.vercel.app/api/flow/health
# Look at: age_seconds field
```

**Fix:**

```bash
# Restart pusher manually
cd $env:USERPROFILE\tape
.\start_flow_pusher.bat

# Wait 10 seconds, then verify
tasklist | findstr pythonw

# Check dashboard - badge should flip to ● LIVE within 10 seconds
```

**Prevention:** The watchdog script should auto-restart within 5 minutes. Check watchdog is running:

```powershell
Get-ScheduledTask -TaskName "JARVIS Flow Watchdog"
```

---

## Problem: "FIXTURE DATA" Badge on Dashboard

**What it means:** Dashboard is showing test/fixture data, not live data.

**Root causes:**
1. `FLOW_PUSH_URL` environment variable is set to fixture endpoint
2. Pusher is pushing to wrong URL

**Diagnosis:**

```bash
# Check the pusher environment
cat $env:USERPROFILE\tape\.env | findstr FLOW_PUSH_URL
# Expected: https://jarvis-trader-dashboard.vercel.app/api/flow/ingest
# NOT: /api/flow/fixture
```

**Fix:**

```bash
# Edit .env file
notepad $env:USERPROFILE\tape\.env

# Change FLOW_PUSH_URL to production endpoint:
FLOW_PUSH_URL=https://jarvis-trader-dashboard.vercel.app/api/flow/ingest

# Restart pusher
taskkill /IM pythonw.exe /F
cd $env:USERPROFILE\tape
.\start_flow_pusher.bat
```

---

## Problem: 401 Unauthorized in Pusher Logs

**What it means:** Token mismatch between pusher and dashboard.

**Root causes:**
1. `FLOW_INGEST_TOKEN` mismatch between pusher `.env` and Vercel env vars
2. Token was rotated on one side but not the other

**Diagnosis:**

```bash
# Check pusher token
cat $env:USERPROFILE\tape\.env | findstr FLOW_INGEST_TOKEN

# Check Vercel dashboard:
# Settings → Environment Variables → FLOW_INGEST_TOKEN
# https://vercel.com/mattamundson/jarvis-trader-dashboard/settings/environment-variables
```

**Fix:**

1. Generate new token (if needed):
```bash
openssl rand -base64 32
```

2. Update both locations:
   - Pusher: Edit `$env:USERPROFILE\tape\.env`
   - Vercel: Dashboard → Settings → Environment Variables → FLOW_INGEST_TOKEN

3. Restart pusher:
```bash
taskkill /IM pythonw.exe /F
cd $env:USERPROFILE\tape
.\start_flow_pusher.bat
```

4. Redeploy dashboard if Vercel env var changed (automatic on next push, or manual redeploy)

---

## Problem: 400 Bad Request in Pusher Logs

**What it means:** Data failed quality validation gates.

**Root causes:**
1. Source data file has corrupt/unrealistic values
2. Timestamp is too old or too far in future
3. Bar data is malformed

**Diagnosis:**

```bash
# Check recent pusher logs for validation errors
cat $env:USERPROFILE\tape\logs\push_flow.log | tail -50
# Look for: HTTP 400 responses

# Check source data file
cat $env:USERPROFILE\tape\flow_snapshot.json
# Inspect: ES price (should be 1000-10000), CVD, bars
```

**Common validation failures:**

| Error | Cause | Fix |
|-------|-------|-----|
| ES price unrealistic | Price < 1000 or > 10000 | Check ThinkorSwim connection, verify symbol |
| CVD magnitude unrealistic | abs(CVD) > 10000 | Check tape aggregation logic |
| Price/VWAP divergence | abs(price - vwap) > 100 | Check VWAP calculation |
| No bars | bars1m array is empty | Check bar aggregation in tape script |
| Invalid bars | volume < 0 or high < low | Check bar parsing logic |
| Timestamp age suspicious | timestamp > 5 min old or < -60s | Check system clock, NTP sync |

**Fix:**

1. If system clock is wrong:
```bash
# Sync time (Windows)
w32tm /resync
```

2. If source data is corrupt:
```bash
# Stop pusher
taskkill /IM pythonw.exe /F

# Delete corrupt snapshot
del $env:USERPROFILE\tape\flow_snapshot.json

# Restart tape aggregation script (will regenerate snapshot)
cd $env:USERPROFILE\tape
.\start_tape_aggregator.bat

# Wait 30 seconds, then start pusher
.\start_flow_pusher.bat
```

---

## Problem: Watchdog Not Auto-Recovering

**What it means:** Pusher crashed but watchdog didn't restart it within 5-10 minutes.

**Root causes:**
1. Watchdog task is not running
2. Watchdog script has errors
3. Batch file path is wrong

**Diagnosis:**

```powershell
# Check if watchdog task exists and is enabled
Get-ScheduledTask -TaskName "JARVIS Flow Watchdog"
# Expected: State = Ready, Enabled = True

# Check last run result
Get-ScheduledTaskInfo -TaskName "JARVIS Flow Watchdog"
# Look at: LastRunTime, LastTaskResult (0 = success)

# Check watchdog logs
cat $env:USERPROFILE\tape\logs\watchdog.log | tail -50
```

**Fix:**

```powershell
# If task doesn't exist, recreate it:
$action = New-ScheduledTaskAction -Execute "python" `
  -Argument "C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\tape\watchdog_flow_pusher.py"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable
Register-ScheduledTask `
  -TaskName "JARVIS Flow Watchdog" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings
Start-ScheduledTask -TaskName "JARVIS Flow Watchdog"

# If task exists but not running, start it:
Start-ScheduledTask -TaskName "JARVIS Flow Watchdog"

# Test manually:
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
python scripts\tape\watchdog_flow_pusher.py
```

---

## Problem: Discord Alerts Not Arriving

**What it means:** Cron job or UptimeRobot is not sending alerts.

**Root causes:**
1. Vercel Cron not configured (missing env vars)
2. Discord webhook URL is wrong or expired
3. UptimeRobot monitor is paused

**Diagnosis:**

```bash
# Check Vercel Cron logs
# Go to: https://vercel.com/mattamundson/jarvis-trader-dashboard/logs
# Filter by: /api/cron/check-flow

# Check Vercel env vars
# Go to: https://vercel.com/mattamundson/jarvis-trader-dashboard/settings/environment-variables
# Verify: CRON_SECRET and DISCORD_WEBHOOK_FLOW_ALERTS are set

# Check UptimeRobot
# Go to: https://uptimerobot.com/dashboard
# Verify: JARVIS Flow Health monitor is UP and not paused
```

**Fix:**

1. If Vercel Cron is failing:
```bash
# Generate new CRON_SECRET
openssl rand -base64 32

# Add to Vercel: Settings → Environment Variables
CRON_SECRET=<generated value>

# Redeploy (automatic on next push)
```

2. If Discord webhook is broken:
   - Discord Server → Channel → Settings → Integrations → Webhooks
   - Delete old webhook, create new one
   - Copy new URL
   - Update Vercel env var: `DISCORD_WEBHOOK_FLOW_ALERTS`
   - Update UptimeRobot alert contact with new webhook URL

3. If UptimeRobot is paused:
   - UptimeRobot Dashboard → JARVIS Flow Health → Resume Monitoring

---

## Command Reference

### Check Status
```bash
# Health endpoint
curl https://jarvis-trader-dashboard.vercel.app/api/flow/health

# Dashboard (browser)
open https://jarvis-trader-dashboard.vercel.app

# Is pusher running?
tasklist | findstr pythonw

# Is watchdog running?
Get-ScheduledTask -TaskName "JARVIS Flow Watchdog"
```

### Restart Services
```bash
# Restart pusher
taskkill /IM pythonw.exe /F
cd $env:USERPROFILE\tape
.\start_flow_pusher.bat

# Restart watchdog
Stop-ScheduledTask -TaskName "JARVIS Flow Watchdog"
Start-ScheduledTask -TaskName "JARVIS Flow Watchdog"

# Manual watchdog run (test)
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
python scripts\tape\watchdog_flow_pusher.py
```

### View Logs
```bash
# Pusher logs
cat $env:USERPROFILE\tape\logs\push_flow.log | tail -50

# Watchdog logs
cat $env:USERPROFILE\tape\logs\watchdog.log | tail -50

# Vercel logs (browser)
open https://vercel.com/mattamundson/jarvis-trader-dashboard/logs
```

---

## Escalation Path

If none of the above fixes work:

1. Check `#flow-alerts` Discord channel for patterns
2. Check Vercel deployment status: https://vercel.com/mattamundson/jarvis-trader-dashboard
3. Check GitHub Actions status: https://github.com/mattamundson/jarvis-trader/actions
4. File issue: https://github.com/mattamundson/jarvis-trader/issues/new

Include in the issue:
- Dashboard screenshot showing the badge state
- Last 50 lines of pusher logs
- Last 50 lines of watchdog logs
- Output of `curl` to health endpoint
- Output of `tasklist | findstr pythonw`
