# IB Gateway Paper Mode Reconnect Runbook

**Date:** 2026-04-10  
**Engine Port:** 8010  
**IB Gateway Port (paper):** 4002  
**Environment:** Windows 11  

---

## Current State

IB Gateway is **NOT running** on port 4002. Engine `/health` reports `"ibkr_connected": false`.

Verify with PowerShell:
```powershell
netstat -ano | Select-String ':4002'
# Expected: (empty output = Gateway down)
```

---

## Prerequisites

**Software Required:**
- **IB Gateway** (NOT TWS desktop app) — download from [Interactive Brokers IB Gateway installer page](https://www.interactivebrokers.com/en/trading/system-requirements.php)
- Windows 11 local admin access
- IB Paper Trading Account credentials (DUP662235 per engine/.env)

**Installation:**
1. Download latest IB Gateway for Windows
2. Run installer with default paths (typically `C:\Jts\` or `C:\Program Files\IB\`)
3. Launch IB Gateway app (separate from TWS)

---

## Step-by-Step Start: IB Gateway Paper Mode

### 1. Launch IB Gateway

Run the IB Gateway executable on your machine. The application window opens with login screen.

### 2. Log In

- **Account:** DUP662235 (or your paper trading account ID)
- **Password:** (your IB password)
- **Authentication:** Complete 2FA if prompted (SMS, security code, etc.)
- **Connection:** Select **Paper Trading** (do NOT select Live Trading)

### 3. Configure API Settings

Once logged in to IB Gateway:

1. Navigate: **File > Global Configuration** (or **Settings > API**).
2. Locate **API** section (left sidebar or tabs).
3. Enable the following:
   - **ActiveX and Socket Clients** — set to **ON**
   - **Socket port** — set to **4002** (paper mode)
   - **Trusted IPs** — add **127.0.0.1** (localhost)
4. **Accept** and **OK** to save.
5. Do NOT enable port **4001** (live port is permanently blocked during Phase 1).

### 4. Confirm Connection

IB Gateway status bar should show:

- **Connected** (top of window)
- **Account: DUP662235**
- **Paper Trading** (clearly labeled)
- No red error icons

---

## Verify Engine Recognizes IB Gateway

After IB Gateway is running on 4002, restart the engine:

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
.\restart_engine.ps1
```

Wait ~10 seconds for startup. Then test the health endpoint:

```powershell
$env:API_KEY = "${JARVIS_API_KEY}"  # from engine/.env

curl.exe -s `
  -H "X-API-Key: $env:API_KEY" `
  http://127.0.0.1:8010/health | ConvertFrom-Json | Format-List

# Expect:
# ibkr_connected : True      <-- SUCCESS
# ibkr_host      : 127.0.0.1
# ibkr_port      : 4002
```

If `ibkr_connected` is still `False`, proceed to **Troubleshooting**.

---

## Troubleshooting — 5 Common Issues

### 1. Port 4002 Conflict

**Symptom:** IB Gateway won't start, or engine logs show "Address already in use 4002".

**Fix:**
```powershell
Get-Process | Where-Object {$_.ProcessName -like '*Gateway*' -or $_.ProcessName -like '*tws*'} | Stop-Process -Force
# Wait 5 seconds
# Re-launch IB Gateway
```

### 2. Client ID Mismatch

**Symptom:** Engine logs: "Connection refused" or "Authentication failed".

**Check in engine/.env:**
```
IBKR_CLIENT_ID=228
```

If changed, update and restart engine:
```powershell
.\restart_engine.ps1
```

**Note:** Client ID 228 is single-instance. Each engine process must use a unique ID (228, 229, 230, etc.). If running multiple engine instances, increment IBKR_CLIENT_ID.

### 3. Account Not Paper Mode

**Symptom:** IB Gateway logs in but engine reports "live trading denied" or "account type error".

**Fix:**
- In IB Gateway: **File > Account > Paper Trading** — confirm explicitly selected.
- Verify engine `.env`:
  ```
  IBKR_PAPER_MODE=True
  PAPER_TRADING=True
  ```

### 4. Two-Factor Authentication Stuck

**Symptom:** IB Gateway login loop, won't proceed past 2FA.

**Fix:**
- Complete 2FA prompt (SMS, app code, or security question).
- If prompt disappears, close IB Gateway and re-launch.
- Confirm SMS/email 2FA device has signal (battery, network).

### 5. Firewall Blocking Localhost

**Symptom:** "Connection timeout" or "ECONNREFUSED 127.0.0.1:4002" in engine logs.

**Fix:**
```powershell
# Check if Windows Firewall allows IB Gateway inbound
netsh advfirewall firewall show rule name="*IB Gateway*" | Select-String "Enabled"

# If disabled, enable (admin required)
netsh advfirewall firewall set rule name="*IB Gateway*" new enabled=yes

# Alternative: Add localhost to firewall exceptions
netsh advfirewall firewall add rule name="IB Gateway Paper Port 4002" `
  dir=in action=allow protocol=tcp localport=4002 remoteip=127.0.0.1 enable=yes
```

---

## Rollback / Halt

If IB Gateway reconnect destabilizes the system:

### Stop IB Gateway

```powershell
Get-Process | Where-Object {$_.ProcessName -like '*Gateway*'} | Stop-Process -Force
```

Engine will automatically switch to **paper simulation mode** (dry-run, no actual orders) and continue running. Health will show:

```
ibkr_connected : False
status : WARNING
```

### Restart Engine (safe mode)

```powershell
.\restart_engine.ps1
```

Engine remains stable in paper simulation mode. No live orders affected.

### Resume Connection

Once IB Gateway issues are resolved, restart engine and IB Gateway again per **Step-by-Step Start** section above.

---

## Health API Contract

After reconnection, the `/health` endpoint returns:

```json
{
  "status": "healthy",
  "timestamp": "2026-04-10T14:30:22Z",
  "ibkr_connected": true,
  "ibkr_host": "127.0.0.1",
  "ibkr_port": 4002,
  "ibkr_account": "DUP662235",
  "ibkr_paper_mode": true,
  "engine": "running",
  "database": "connected",
  "agents_ready": 5
}
```

**Key fields to verify:**
- `ibkr_connected: true` — Gateway is responding
- `ibkr_port: 4002` — Paper mode port confirmed
- `ibkr_paper_mode: true` — Live trading NOT active

---

## Dashboard Verification

Once engine reports `ibkr_connected: true`:

1. Open dashboard: http://localhost:3010
2. Navigate to **Settings > Safety** page
3. Confirm `IB Gateway Status` shows **Connected**
4. Verify **Account Balance** displays correctly (should be paper account balance)

If dashboard still shows disconnected despite engine health being true, clear browser cache:

```powershell
# Close browser, then
Remove-Item -Path "$env:APPDATA\Local\<YourBrowser>\Cache" -Recurse -Force
```

---

## Reference Docs

- **IB Connector Behavior:** `docs/runbooks/IB_CONNECTOR_OVERVIEW.md`
- **Health API Contract:** `docs/runbooks/HEALTH_API_CONTRACT.md`
- **Paper Trading Setup:** `docs/runbooks/PAPER_TRADING.md`
- **Connector Code:** `engine/execution/ib_gateway_connector.py`
- **Engine Health Endpoint:** `engine/routers/health_router.py`

---

**Last Updated:** 2026-04-10  
**Audience:** Phase 1 operators (Matt, agents requiring manual IB Gateway restart)  
**Tier:** Operational / Manual Intervention Required
