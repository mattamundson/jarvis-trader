/**
 * JARVIS TRADER — PM2 Process Manager Configuration
 * ==================================================
 * Manages all JARVIS Trader processes on Windows (port 8010).
 *
 * Usage:
 *   pm2 start ecosystem.config.js                   # Start all processes
 *   pm2 start ecosystem.config.js --only jarvis-engine
 *   pm2 start ecosystem.config.js --only jarvis-rolling-wfe
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
 *   jarvis-engine:       8010 (FastAPI)
 *   jarvis-rolling-wfe:  cron (no port — scheduler only)
 *
 * @see JARVIS_TRADER_MASTER.md §1.14 Infrastructure
 * @see engine/backtest/rolling_wfe_scheduler.py
 */

const path = require("path");

// Absolute path to the engine directory (resolves relative to this config file)
const ENGINE_DIR = __dirname;
const PYTHON = path.join(ENGINE_DIR, ".venv", "Scripts", "python.exe");

module.exports = {
  apps: [
    // ── FastAPI Engine ─────────────────────────────────────────────────────────
    {
      name: "jarvis-engine",
      script: PYTHON,
      args: "-m uvicorn main:app --host 0.0.0.0 --port 8010 --reload",
      cwd: ENGINE_DIR,
      interpreter: "none",

      // Environment
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      // Restart policy
      autorestart: true,
      watch: false,            // Do NOT watch — uvicorn --reload handles file changes
      max_restarts: 10,
      min_uptime: "30s",       // Must stay up 30s to count as "started"
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

    // ── Dashboard (Next.js) — OPTIONAL: use if not running dashboard separately ──
    // Uncomment to manage dashboard via PM2 as well.
    // {
    //   name: "jarvis-dashboard",
    //   script: "node",
    //   args: "node_modules/.bin/next start -p 3010",
    //   cwd: path.join(ENGINE_DIR, "..", "dashboard"),
    //   interpreter: "none",
    //   autorestart: true,
    //   watch: false,
    //   env: { NODE_ENV: "production", PORT: "3010" },
    //   log_date_format: "YYYY-MM-DD HH:mm:ss",
    // },
  ],
};
