# Live ES Order Flow Pusher

This script pushes live ES order flow data from Matt's Windows PC to the Vercel-hosted dashboard.

## Overview

The pusher script (`push_flow.py`) runs continuously in the background, reading flow snapshot JSON every 5 seconds and POSTing it to the dashboard's ingest endpoint. Data is sanitized before transmission to strip account IDs, dollar amounts, and positions.

## Environment Variables

Set these in Windows environment variables or a `.env` file:

- `FLOW_PUSH_URL`: The dashboard ingest endpoint URL (e.g., `https://your-dashboard.vercel.app/api/flow/ingest`)
- `FLOW_INGEST_TOKEN`: Bearer token for authentication (must match `FLOW_INGEST_TOKEN` set on Vercel)
- `FLOW_SNAPSHOT_PATH`: Path to flow snapshot JSON file (default: `~\tape\state\flow-latest.json` which expands to your user profile)

The dashboard also requires:
- `FLOW_INGEST_TOKEN`: Same token as above
- `BLOB_READ_WRITE_TOKEN`: Vercel Blob storage token (automatically set by Vercel when you create a Blob store)

## Running as a Windows Scheduled Task

To run the pusher script as a hidden background task:

### 1. Create a batch wrapper

Create `start_flow_pusher.bat` in your preferred location (e.g., `C:\tape\start_flow_pusher.bat`):

```batch
@echo off
set FLOW_PUSH_URL=https://your-dashboard.vercel.app/api/flow/ingest
set FLOW_INGEST_TOKEN=your-secret-token-here
set FLOW_SNAPSHOT_PATH=%USERPROFILE%\tape\state\flow-latest.json
pythonw "C:\workspace\jarvis-trader\scripts\tape\push_flow.py"
```

Replace `your-dashboard.vercel.app` and `your-secret-token-here` with your actual values. Adjust `FLOW_SNAPSHOT_PATH` if your flow snapshot is elsewhere (the default is `~\tape\state\flow-latest.json`).

**Important:** Use `pythonw` (not `python`) to run without showing a console window.

### 2. Create a scheduled task

Open Task Scheduler and create a new task:

1. **General tab:**
   - Name: `JARVIS Flow Pusher`
   - Description: `Pushes live ES order flow to Vercel dashboard`
   - Run whether user is logged on or not: ✓
   - Run with highest privileges: ✓

2. **Triggers tab:**
   - Click "New..."
   - Begin the task: `At startup`
   - Delay task for: `30 seconds` (wait for network/services)
   - Enabled: ✓

3. **Actions tab:**
   - Click "New..."
   - Action: `Start a program`
   - Program/script: Full path to your `start_flow_pusher.bat` (e.g., `C:\tape\start_flow_pusher.bat`)
   - Start in: Directory containing the batch file (e.g., `C:\tape`)

4. **Conditions tab:**
   - Start the task only if the computer is on AC power: ✗ (uncheck)
   - Stop if the computer switches to battery power: ✗ (uncheck)

5. **Settings tab:**
   - Allow task to be run on demand: ✓
   - If the running task does not end when requested, force it to stop: ✓
   - If the task is already running, do not start a new instance: ✓

### 3. Verify it's running

After reboot or manually starting the task:

1. Open Task Scheduler
2. Find "JARVIS Flow Pusher" in the task list
3. Check the "Status" column shows "Running"
4. Check the dashboard at `https://your-dashboard.vercel.app/flow` to verify live data (should not show "FIXTURE" badge)

### 4. Stop the task

To stop the pusher:

1. Open Task Scheduler
2. Right-click "JARVIS Flow Pusher"
3. Select "End"

Or use PowerShell:

```powershell
Stop-ScheduledTask -TaskName "JARVIS Flow Pusher"
```

## Logging

The script logs failures to stdout. To capture logs, modify the batch file:

```batch
@echo off
set FLOW_PUSH_URL=https://your-dashboard.vercel.app/api/flow/ingest
set FLOW_INGEST_TOKEN=your-secret-token-here
set FLOW_SNAPSHOT_PATH=%USERPROFILE%\tape\state\flow-latest.json
python "C:\workspace\jarvis-trader\scripts\tape\push_flow.py" >> "%USERPROFILE%\tape\logs\flow_pusher.log" 2>&1
```

**Note:** This uses `python` (not `pythonw`) to enable logging, so the console window will appear. If you want hidden + logging, keep `pythonw` and the script will only log errors internally (silent success).

## Testing Locally

Before setting up the scheduled task, test the script manually:

```powershell
cd C:\workspace\jarvis-trader\scripts\tape
$env:FLOW_PUSH_URL = "https://your-dashboard.vercel.app/api/flow/ingest"
$env:FLOW_INGEST_TOKEN = "your-secret-token-here"
$env:FLOW_SNAPSHOT_PATH = "$env:USERPROFILE\tape\state\flow-latest.json"
python push_flow.py
```

You should see:
```
[INFO] Watching <path-to-your-flow-snapshot>
[INFO] Pushing to https://your-dashboard.vercel.app/api/flow/ingest
```

Then check the dashboard at `/flow` to verify the data appears.

## Security Notes

- The `FLOW_INGEST_TOKEN` is a shared secret between the pusher and the dashboard. Keep it secure.
- Never commit the token to git. Store it in environment variables or a gitignored `.env` file.
- The dashboard sanitizes all incoming data to strip account IDs, dollar amounts, and positions before storage.
- Data is stored in Vercel Blob with public read access (anonymous users can view the public order flow page).

## Troubleshooting

### Script not starting
- Check that `pythonw` is in PATH: `where pythonw`
- Verify the batch file paths are correct
- Check Task Scheduler's "Last Run Result" for error codes

### Data not appearing on dashboard
- Verify your flow snapshot JSON exists and is being updated
- Check the dashboard's Vercel logs for ingest errors
- Verify the dashboard shows data but no "FIXTURE" badge (fixture = fake data)
- Test the endpoint manually with curl:
  ```powershell
  curl -X POST https://your-dashboard.vercel.app/api/flow/ingest `
    -H "Authorization: Bearer your-token-here" `
    -H "Content-Type: application/json" `
    -d "@$env:USERPROFILE\tape\state\flow-latest.json"
  ```

### Script crashes on startup
- The script never crashes on missing files (it waits)
- Check that both environment variables are set
- Run manually (not via scheduled task) to see error messages
