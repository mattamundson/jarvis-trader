# Engine Restart Checklist

## After Training Completes — Before Restart
1. Note Run 5 results (all metrics)
2. Decide which scenario applies (A/B/C/D)
3. Edit rl_config.py with appropriate REWARD_CONFIG change

## Restart Commands
```bash
# Kill all Python processes
taskkill //F //IM python3.12.exe //IM python.exe

# Verify port is clear
netstat -ano | grep ":8010 " | grep LISTEN || echo "Port clear"

# Start engine with venv Python (CRITICAL: must use .venv, not system Python)
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/engine
nohup .venv/Scripts/python.exe -m uvicorn main:app --port 8010 > /tmp/engine.log 2>&1 &

# Wait and verify
sleep 5 && curl -s http://localhost:8010/health
```

## Post-Restart Verifications
1. Engine uses venv Python: `netstat -ano | grep :8010` → check PID → `Get-Process -Id PID | Select Path`
2. Health check: `curl http://localhost:8010/health` → status: ok
3. PnLMonitor starting_balance: `curl http://localhost:8010/health/full` → pnl_monitor.starting_balance > 0
4. Circuit breakers clear: overall = "healthy" (not "circuit_breaker_tripped")
5. Preflight: `curl http://localhost:8010/system/preflight` → not null
6. Models list: `curl http://localhost:8010/rl/models` → returns list (not 500)
