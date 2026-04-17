/**
 * JARVIS TRADER — PM2 Process Manager Configuration
 * ==================================================
 * Manages all JARVIS Trader processes on Windows (port 8010).
 *
 * Usage:
 *   pm2 start ecosystem.config.js                   # Start all processes
 *   pm2 start ecosystem.config.js --only jarvis-engine
 *   pm2 start ecosystem.config.js --only jarvis-morning-brief
 *   pm2 stop all
 *   pm2 restart jarvis-engine
 *   pm2 logs jarvis-engine
 *   pm2 save                                         # Persist on reboot
 *   pm2 startup                                      # Auto-start on boot
 *
 * Prerequisites:
 *   - Node.js 18+ installed (for PM2)
 *   - npm install -g pm2
 *   - Python venv at engine/.venv/ (created via: cd engine && python -m venv .venv)
 *   - Dependencies installed: .venv/Scripts/pip install -r requirements-core.txt
 *
 * Ports:
 *   jarvis-engine:           8010 (FastAPI)
 *   jarvis-rolling-wfe:      cron (no port — scheduler only)
 *   jarvis-paper-runner:     cron (no port — scheduler only)
 *   jarvis-health-check:     cron (no port — health monitoring)
 *   jarvis-morning-brief:    cron (no port — pre-market brief)
 *   jarvis-eod-summary:      cron (no port — end-of-day journal)
 *
 * @see JARVIS_TRADER_MASTER.md §1.14 Infrastructure
 * @see engine/scripts/daily_health_check.py
 * @see engine/scripts/morning_brief.py
 * @see engine/scripts/eod_summary.py
 */

const path = require("path");

// Absolute path to the engine directory (resolves relative to this config file)
const ENGINE_DIR = __dirname;
const PYTHON = path.join(ENGINE_DIR, ".venv", "Scripts", "python.exe");

module.exports = {
  apps: [
    // ── FastAPI Engine ─────────────────────────────────────────────────────────
    // NOTE: launched via scripts/port_guardian.py instead of uvicorn directly.
    // Guardian kills any orphaned python/uvicorn process holding port 8010 before
    // exec'ing uvicorn. Prevents the 2026-04-14 crash-loop class of bug where a
    // PowerShell-launched orphan blocks PM2 restarts. See docs/troubleshooting.md.
    {
      name: "jarvis-engine",
      script: PYTHON,
      args: "scripts/port_guardian.py",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Restart policy — no --reload so PM2 is the sole restart mechanism
      autorestart: true,
      watch: false,
      max_restarts: 50,
      min_uptime: "10s",
      restart_delay: 5000,     // Wait 5s between restarts

      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "engine-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "engine-out.log"),
      merge_logs: true,
      log_type: "json",

      // Windows-specific: set interpreter to none so PM2 runs the script directly
      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Rolling WFE Scheduler ──────────────────────────────────────────────────
    // Runs every Monday at 6:00 AM to recalculate walk-forward efficiency.
    // Checks if 28+ days have passed since last run before triggering WFE.
    // Sends WhatsApp alert if any instrument WFE drops below halt threshold.
    // Exit 1 → paper trading review required.
    {
      name: "jarvis-rolling-wfe",
      script: PYTHON,
      args: "-m backtest.rolling_wfe_scheduler",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Cron: run every Monday at 06:00 (local machine time)
      // This is a one-shot cron job (not a daemon) — autorestart must be false.
      cron_restart: "0 6 * * 1",
      autorestart: false,

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "rolling-wfe-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "rolling-wfe-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Daily Health Check ─────────────────────────────────────────────────────
    // Validates engine health, safety status, and portfolio equity.
    // Runs every 30 minutes during market hours (8:00am–5:00pm CT Mon–Fri).
    // Logs to data/daily_health_log.json.
    {
      name: "jarvis-health-check",
      script: PYTHON,
      args: "scripts/daily_health_check.py",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Cron: every 30 minutes during market hours (8:00am–5:00pm CT)
      // */30 8-16 * * 1-5 in CT (note: PM2 uses cron_restart for cron scheduling)
      cron_restart: "*/30 8-16 * * 1-5",
      autorestart: false,

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "health-check-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "health-check-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Pre-Market Intelligence Brief ──────────────────────────────────────────
    // Generates market snapshot, VIX regime, sentiment, and portfolio status.
    // Runs daily at 6:30am CT (2 hours before RTH open at 8:30am CT).
    // Saves brief to data/morning_briefs/YYYY-MM-DD.md.
    {
      name: "jarvis-morning-brief",
      script: PYTHON,
      args: "scripts/morning_brief.py",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Cron: every weekday at 06:30 CT
      cron_restart: "30 6 * * 1-5",
      autorestart: false,

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "morning-brief-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "morning-brief-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── End-of-Day Summary ─────────────────────────────────────────────────────
    // Generates daily journal entry with trades, P&L, and learning insights.
    // Runs daily at 4:05pm CT (5 minutes after RTH close at 4:00pm CT).
    // Saves journal to data/daily_journals/YYYY-MM-DD.md.
    {
      name: "jarvis-eod-summary",
      script: PYTHON,
      args: "scripts/eod_summary.py",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Cron: every weekday at 16:05 CT (4:05pm CT)
      cron_restart: "5 16 * * 1-5",
      autorestart: false,

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "eod-summary-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "eod-summary-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Next.js Dashboard ─────────────────────────────────────────────────────
    // Serves the React dashboard at http://localhost:3010
    // Uses pnpm start (production build) — run `pnpm build` in dashboard/ first.
    {
      name: "jarvis-dashboard",
      script: "pnpm",
      args: "run start",
      cwd: path.join(ENGINE_DIR, "..", "dashboard"),
      interpreter: "none",

      autorestart: true,
      watch: false,
      max_restarts: 10,
      min_uptime: "10s",
      restart_delay: 3000,

      env: {
        NODE_ENV: "production",
        PORT: "3010",
      },

      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "dashboard-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "dashboard-out.log"),
      merge_logs: true,
      exec_mode: "fork",
    },
  ],
};
