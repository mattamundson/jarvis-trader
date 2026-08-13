# JARVIS TRADER — Launch Scripts

Comprehensive PowerShell scripts for managing the paper trading system startup and shutdown with extensive safety verification.

---

## Quick Start

```powershell
# Launch paper trading with full preflight checks
.\scripts\launch_paper_trading.ps1

# Stop paper trading cleanly
.\scripts\stop_paper_trading.ps1
```

---

## launch_paper_trading.ps1

Performs 7 phases of validation and startup before launching the paper trading system. Aborts immediately on ANY safety check failure.

### Phases

#### PHASE 1: Preflight Dependency Checks
- **Java**: Verifies JRE 11+ (required for IB Gateway)
- **Node.js**: Confirms Node.js installation (required for PM2 and dashboard)
- **PM2**: Checks PM2 is installed globally
- **Python venv**: Validates `engine\.venv\Scripts\python.exe` exists

#### PHASE 2: Environment Configuration Validation
- **`.env` file**: Confirms `engine\.env` exists
- **Required variables**: Validates ANTHROPIC_API_KEY, POSTGRES_URL, IBKR_PORT are set
- **No placeholders**: Rejects any `YOUR_*`, `*_HERE`, or example values
- **CRITICAL**: Aborts if PAPER_TRADING != True
- **CRITICAL**: Aborts if LIVE_TRADING_ENABLED != False

#### PHASE 3: Infrastructure Checks
- **Docker**: Checks Docker daemon is running (warns if not)
- **Postgres**: Verifies container running (optional)
- **Redis**: Verifies container running (optional)
- **IB Gateway**: Tests TCP connectivity on 127.0.0.1:7497 (can skip with `-SkipIBCheck`)

#### PHASE 4: Safety Verification
- **config.py**: Reads and confirms LIVE_TRADING_ENABLED default is False
- **safety_layer.py**: Validates file exists and is not empty (>1000 bytes)
- **Kill switch thresholds**: Confirms `MAX_DAILY_LOSS_PCT`/`MAX_DRAWDOWN_PCT` are wired in `safety_layer.py` (currently -6% daily / -20% drawdown per `config.py`)

#### PHASE 5: Test Suite Execution (default enabled)
- **Safety layer tests**: Runs `pytest tests\test_safety_layer.py -v`
- **CRITICAL**: Aborts if ANY tests fail
- **Skip with**: `.\scripts\launch_paper_trading.ps1 -SkipTests` (development only)

#### PHASE 6: Launch Sequence
1. **Start engine**: `pm2 start ecosystem.config.js --only jarvis-engine`
2. **Wait**: 10 seconds for initialization
3. **Health check**: Polls `http://localhost:8010/health` (max 30 retries, 2s intervals)
4. **Start dashboard**: `pnpm dev` in background
5. **Abort if**: Health check fails after 30 attempts

#### PHASE 7: Post-Launch Verification
- **GET /health**: Confirms engine is responding
- **GET /safety/status**: Checks kill switch status and paper mode
- **GET /portfolio**: Retrieves starting equity
- **Open browser**: Launches http://localhost:3010 in default browser

### Usage

```powershell
# Standard launch
.\scripts\launch_paper_trading.ps1

# Skip test suite (development only)
.\scripts\launch_paper_trading.ps1 -SkipTests

# Skip IB Gateway check (if not running yet)
.\scripts\launch_paper_trading.ps1 -SkipIBCheck

# Combine options
.\scripts\launch_paper_trading.ps1 -SkipTests -SkipIBCheck
```

### Color-Coded Output

- **Green**: Pass — check succeeded
- **Red**: Fail — check failed, causes abort
- **Yellow**: Warn — issue detected but non-critical
- **Cyan**: Info — informational message
- **Magenta**: Header — section divider

### Error Handling

The script aborts immediately on:
- Missing Java, Node.js, PM2, or Python venv
- Missing or invalid `.env` file
- PAPER_TRADING != True
- LIVE_TRADING_ENABLED != False
- Engine health check failure
- Safety layer test failures

### Safety Invariants

The script enforces critical safety rules from `.claude/rules/safety.md`:

```
LIVE_TRADING_ENABLED = False     (hardcoded — never True in paper phase)
REQUIRE_HUMAN_APPROVAL = True     (always enforced)
PAPER_TRADING = True              (must be enabled)
Kill switch: -6% daily / -20% drawdown     (non-negotiable)
```

---

## stop_paper_trading.ps1

Cleanly shuts down all JARVIS TRADER processes with status logging.

### Shutdown Sequence

1. **PM2 stop all**: Gracefully stops all processes managed by PM2
2. **Kill dashboard**: Terminates background pnpm process if running
3. **Verify termination**: Checks all processes are offline
4. **Clean up**: Removes dashboard PID file

### Usage

```powershell
# Stop all processes
.\scripts\stop_paper_trading.ps1
```

### Output

Displays:
- Shutdown timestamp
- Shutdown duration
- Process status (Engine, Dashboard, Rolling WFE)
- Log file locations
- Command to restart

---

## Prerequisites

Before running the launch script:

1. **Java JRE 11+**
   ```powershell
   java -version
   ```

2. **Node.js 18+**
   ```powershell
   node --version
   ```

3. **PM2 globally installed**
   ```powershell
   npm install -g pm2
   ```

4. **Python venv configured**
   ```powershell
   cd engine
   python -m venv .venv
   .venv\Scripts\pip install -r requirements-core.txt
   ```

5. **`.env` file configured**
   ```powershell
   Copy-Item engine\.env.example engine\.env
   # Edit engine\.env with real values
   ```

6. **Docker running** (optional but recommended)
   ```powershell
   docker-compose up -d
   ```

7. **IB Gateway running** (for paper trading)
   - Download from Interactive Brokers
   - Extract and run
   - Verify listening on 127.0.0.1:7497

---

## Troubleshooting

### Engine health check fails

```
[FAIL] Engine health check failed after 30 attempts
```

**Solution:**
1. Check engine logs: `type engine\logs\engine-out.log`
2. Verify Python venv: `engine\.venv\Scripts\pip list | findstr fastapi`
3. Verify .env is loaded: `type engine\.env | findstr ANTHROPIC_API_KEY`
4. Manually test: `curl http://localhost:8010/health`

### Safety layer tests fail

```
[FAIL] Safety layer tests failed (exit code: 1)
```

**Solution:**
1. Run tests manually: `cd engine && .\.venv\Scripts\python -m pytest tests\test_safety_layer.py -v`
2. Check test output for specific failures
3. Do NOT skip safety tests — they are non-negotiable

### PM2 fails to start

```
[FAIL] PM2 failed to start engine
```

**Solution:**
1. Verify PM2 is installed: `pm2 --version`
2. Check ecosystem.config.js is valid: `pm2 validate`
3. View PM2 logs: `pm2 logs jarvis-engine`
4. Try manual start: `cd engine && .\.venv\Scripts\python -m uvicorn main:app --port 8010`

### Dashboard fails to start

**Solution:**
1. Check pnpm is installed: `pnpm --version`
2. Verify dashboard dependencies: `cd dashboard && pnpm install`
3. Check for port conflicts: `netstat -ano | findstr :3010`
4. Try manual start: `cd dashboard && pnpm dev`

### IB Gateway not reachable

```
[WARN] IB Gateway not reachable on 127.0.0.1:7497
```

**Solution:**
1. Verify IB Gateway is running and logged in
2. Check port configuration in IB Gateway settings (should be 7497 for paper)
3. Check firewall allows 127.0.0.1:7497
4. Restart IB Gateway if necessary
5. Use `-SkipIBCheck` flag if IB Gateway startup is not ready yet

### Docker containers not running

```
[WARN] Postgres container not found
```

**Solution:**
1. Start Docker: `docker-compose up -d`
2. Verify: `docker-compose ps`
3. Check logs: `docker-compose logs postgres`

---

## File Locations

| Item | Path |
|------|------|
| Launch script | `scripts/launch_paper_trading.ps1` |
| Stop script | `scripts/stop_paper_trading.ps1` |
| Engine logs | `engine/logs/engine-out.log` |
| Engine errors | `engine/logs/engine-error.log` |
| PM2 config | `engine/ecosystem.config.js` |
| Safety layer | `engine/risk/safety_layer.py` |
| Configuration | `engine/config.py` |
| .env file | `engine/.env` |

---

## Best Practices

1. **Always run full preflight checks**: Don't use `-SkipTests` in production
2. **Monitor logs in parallel**:
   ```powershell
   # In another terminal
   pm2 logs jarvis-engine
   ```
3. **Keep IB Gateway running**: Paper trading requires live market data
4. **Review safety status**: Check `/safety/status` after launch
5. **Save startup output**: Capture logs for debugging if issues occur
6. **Check kill switch**: Verify it's off unless you want to halt trading

---

## Safety Guarantees

The launch script enforces safety through:

1. **Hardcoded Python defaults**: `LIVE_TRADING_ENABLED = False` cannot be overridden
2. **.env validation**: Rejects placeholder values and missing critical vars
3. **Test suite gate**: Aborts if safety_layer tests fail
4. **Phase-by-phase abort**: Fails fast on ANY critical issue
5. **Kill switch verification**: Confirms -6% daily, -20% drawdown limits

These guarantees ensure paper trading cannot accidentally become live trading.

---

## Notes

- Scripts use `Set-StrictMode -Version Latest` for robust error handling
- Color output works in Windows PowerShell 5.0+ and PowerShell 7+
- Dashboard PID is stored in `dashboard-pid.txt` for clean shutdown
- Log timestamps follow ISO 8601 format (YYYY-MM-DD HH:MM:SS)
- All paths are relative to project root (where scripts are called from)

---

## Related Documentation

- `CLAUDE.md` — Project overview and structure
- `.claude/rules/safety.md` — Safety rules (non-negotiable)
- `.claude/rules/testing.md` — Test requirements
- `docs/runbooks/PAPER_TRADING.md` — Paper trading runbook
- `engine/ecosystem.config.js` — PM2 process configuration
