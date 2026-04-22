# JARVIS API Bridge

Live market data server for the Strategy C+ dashboard. FastAPI on port 8020.

## Endpoints

| Endpoint | Description | Cache |
|---|---|---|
| `GET /health` | Liveness check | — |
| `GET /api/quotes?symbols=XLK,QQQ,...` | Live yfinance batch quotes | 25s |
| `GET /api/signal` | Latest Strategy C+ signal JSON | — |
| `GET /api/search?q=NVDA` | Any ticker — price, name, type, market cap | — |
| `GET /api/options?symbol=SPY` | Near-term options chain, ±5% ATM | — |
| `GET /api/pnl` | Paper portfolio mark-to-market P&L | — |
| `GET /api/regime` | Regime + VIX alert flags | — |
| `GET /api/ibkr/status` | IBKR paper account + execution log | — |
| `GET /api/gainers` | Top 5 gainers + losers | 60s |
| `GET /api/macro` | VIX, 10Y yield, GLD, BTC regime signals | 60s |
| `GET /api/alerts` | System alert feed from signal + execution logs | — |
| `GET /api/commentary` | JARVIS macro brief (live VIX + signal aware) | — |

## Windows Quick Start

```powershell
# 1. Navigate to this folder
cd C:\Users\mattm\workspace\jarvis-trader\jarvis_api

# 2. Install dependencies (first time only)
.\deploy\START_WINDOWS.ps1 install

# 3. Start the API
.\deploy\START_WINDOWS.ps1 start

# 4. Auto-start on every login (run once as Administrator)
.\deploy\AUTOSTART_WINDOWS.ps1
```

## Linux / Mac Quick Start

```bash
cd jarvis_api
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8020
```

## Keep Alive — Linux (supervisor)

```bash
./deploy/start_persistent.sh start     # start via supervisor
./deploy/start_persistent.sh status    # check
./deploy/start_persistent.sh logs      # tail logs
./deploy/start_persistent.sh install-systemd  # register as system service
```

## Watchdog Cron (Linux fallback)

```bash
# Add to crontab — checks health every minute, restarts if dead
./deploy/start_persistent.sh install-cron
```
