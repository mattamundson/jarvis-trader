#!/bin/bash
# JARVIS API Watchdog — checks health every 60s, restarts if dead
# Add to crontab: * * * * * /home/user/workspace/jarvis_api/deploy/watchdog.sh

API_URL="http://localhost:8020/health"
LOG="/home/user/workspace/jarvis_api/logs/watchdog.log"
PID_FILE="/home/user/workspace/jarvis_api/jarvis_api.pid"
WORK_DIR="/home/user/workspace/jarvis_api"

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Check if API is responding
if curl -sf --max-time 5 "$API_URL" > /dev/null 2>&1; then
    echo "$(timestamp) [OK] JARVIS API healthy" >> "$LOG"
    exit 0
fi

echo "$(timestamp) [WARN] JARVIS API not responding — attempting restart..." >> "$LOG"

# Kill any existing process on port 8020
EXISTING_PID=$(lsof -ti:8020 2>/dev/null)
if [ -n "$EXISTING_PID" ]; then
    kill -9 $EXISTING_PID 2>/dev/null
    sleep 2
fi

# Restart
cd "$WORK_DIR"
nohup /usr/local/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8020 > \
    "$WORK_DIR/logs/jarvis_api.log" 2>&1 &

NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
echo "$(timestamp) [RESTART] JARVIS API started with PID $NEW_PID" >> "$LOG"

# Verify it came up
sleep 5
if curl -sf --max-time 5 "$API_URL" > /dev/null 2>&1; then
    echo "$(timestamp) [OK] Restart successful — PID $NEW_PID" >> "$LOG"
else
    echo "$(timestamp) [ERROR] Restart FAILED — check logs" >> "$LOG"
fi
