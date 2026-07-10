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
 *   jarvis-bridge-api:       8020 (FastAPI quotes/options bridge)
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
      // 2026-07-10: raised 5s -> 15s. port_guardian_restarts.jsonl showed a
      // continuous orphan-kill loop (03:52-04:55 UTC, ~20 cycles) under heavy
      // host contention (900-1100+ processes, <1.3GB free RAM): every restart
      // found a still-live python process holding port 8010 and had to force-kill
      // it, meaning the prior attempt's shutdown hadn't finished releasing the
      // port within the old 5s window. 15s gives teardown more room under
      // contention; env-tunable knobs already exist for the separate slow-boot
      // path (PORT_GUARDIAN_READINESS_DEADLINE / _PROBE_TIMEOUT in
      // port_guardian.py) but not for this restart-cadence path until now.
      restart_delay: 15000,

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

    // ── Weekly Paper Tearsheet (US-007, 2026-06-12) ───────────────────────────
    // QuantStats tearsheet + METRICS_SNAPSHOT.json for the paper account so QS
    // history accumulates without manual runs. Saturday 07:00 (after Friday close).
    {
      name: "jarvis-weekly-tearsheet",
      script: PYTHON,
      args: path.join(ENGINE_DIR, "..", "scripts", "jarvis_tearsheet.py") + " --source paper",
      cwd: ENGINE_DIR,
      interpreter: "none",
      cron_restart: "0 7 * * 6",
      autorestart: false,
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "weekly-tearsheet-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "weekly-tearsheet-out.log"),
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

    // ── Nightly Discord Export + Ingest ────────────────────────────────────────
    // Runs DiscordChatExporter on the two live Corey channels (general,
    // market-updates), then chains into nightly_discord.py to ingest the fresh
    // JSON into SQLite + run sentiment ETL. Closes T2.1 staleness (agents were
    // reading discord_corey_commentary that was 15 days stale).
    //
    // Prereqs (user action): install DiscordChatExporter.Cli to
    // C:\Users\mattm\tools\DiscordChatExporter.Cli\ (or set DCE_CLI_PATH env).
    //
    // Runs nightly at 02:00 America/Chicago — after all US sessions close,
    // before morning-brief at 06:30. --after=7d keeps per-run payload <5 MB.
    {
      name: "jarvis-discord-export",
      script: PYTHON,
      args: "-m scripts.nightly_discord_export",
      cwd: ENGINE_DIR,
      interpreter: "none",

      cron_restart: "0 2 * * *",
      autorestart: false,

      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
        TZ: "America/Chicago",
      },

      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "discord-export-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "discord-export-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Vault: Daily Synthesis Brief (#1) ─────────────────────────────────────
    // 06:00 CT — Claude reads the last 7 days of vault notes and writes a
    // synthesis (connections / pattern / contradiction / best capture) to
    // 00-Inbox/brief-YYYY-MM-DD.md. Inert unless ENABLE_VAULT_SYNTHESIS=1.
    {
      name: "jarvis-vault-synthesis",
      script: PYTHON,
      args: "scripts/vault_synthesis_brief.py",
      cwd: ENGINE_DIR,
      interpreter: "none",
      cron_restart: "0 6 * * *",
      autorestart: false,
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
        TZ: "America/Chicago",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "vault-synthesis-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "vault-synthesis-out.log"),
      merge_logs: true,
      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Vault: Wikilink Lint Pass ─────────────────────────────────────────────
    // 06:30 CT — structural integrity scan (no LLM): finds broken [[wikilinks]]
    // and orphan notes, writes 00-Inbox/lint-YYYY-MM-DD.md. Inert unless
    // ENABLE_VAULT_LINT=1.
    {
      name: "jarvis-vault-lint",
      script: PYTHON,
      args: "scripts/vault_lint.py",
      cwd: ENGINE_DIR,
      interpreter: "none",
      cron_restart: "30 6 * * *",
      autorestart: false,
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
        TZ: "America/Chicago",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "vault-lint-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "vault-lint-out.log"),
      merge_logs: true,
      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Vault: Thesis Contradiction Check (#5) ────────────────────────────────
    // 07:00 CT — Claude scans 02-Theses against the last 30 days of 01-Sources
    // for conflict only, writes 00-Inbox/contradictions-YYYY-MM-DD.md. Inert
    // unless ENABLE_VAULT_CONTRADICTION=1.
    {
      name: "jarvis-vault-contradiction",
      script: PYTHON,
      args: "scripts/vault_contradiction_check.py",
      cwd: ENGINE_DIR,
      interpreter: "none",
      cron_restart: "0 7 * * *",
      autorestart: false,
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
        TZ: "America/Chicago",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "vault-contradiction-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "vault-contradiction-out.log"),
      merge_logs: true,
      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Vault: Midnight GitHub Backup (#9) ────────────────────────────────────
    // 00:00 CT — commits + pushes the Obsidian vault (its own git repo at the
    // vault root, NOT this repo) to its private remote. Inert unless
    // ENABLE_VAULT_BACKUP=1 and the vault has been `git init`'d with a remote.
    {
      name: "jarvis-vault-backup",
      script: PYTHON,
      args: "scripts/backup_vault_to_github.py",
      cwd: ENGINE_DIR,
      interpreter: "none",
      cron_restart: "0 0 * * *",
      autorestart: false,
      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
        TZ: "America/Chicago",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "vault-backup-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "vault-backup-out.log"),
      merge_logs: true,
      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── API Bridge (port 8020) ────────────────────────────────────────────────
    // yFinance quotes/regime/options/pnl bridge consumed by the Strategy C+
    // Command Center (dashboard/static/strategy_c_dashboard.html). Was previously
    // unmanaged (audit finding F-9): the Command Center ibkr/options/pnl tabs were
    // dead whenever nobody started it by hand. Bound to 127.0.0.1, no --reload.
    {
      name: "jarvis-bridge-api",
      script: PYTHON,
      args: "-m uvicorn main:app --host 127.0.0.1 --port 8020",
      cwd: path.join(ENGINE_DIR, "api"),
      interpreter: "none",

      autorestart: true,
      watch: false,
      max_restarts: 20,
      min_uptime: "10s",
      restart_delay: 5000,

      env: {
        PYTHONPATH: ENGINE_DIR,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUNBUFFERED: "1",
      },

      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: path.join(ENGINE_DIR, "logs", "bridge-api-error.log"),
      out_file: path.join(ENGINE_DIR, "logs", "bridge-api-out.log"),
      merge_logs: true,

      exec_interpreter: "none",
      exec_mode: "fork",
    },

    // ── Next.js Dashboard ─────────────────────────────────────────────────────
    // Serves the React dashboard at http://localhost:3010
    // Uses pnpm start (production build) — run `pnpm build` in dashboard/ first.
    //
    // NOTE: script must be ``cmd /c pnpm run start`` on Windows, NOT ``pnpm`` directly.
    // PM2 on Node 24 tries to ``require("pnpm.cmd")`` as a JS module and hits
    // ``SyntaxError: Invalid or unexpected token`` on the ``@ECHO off`` line.
    // Wrapping through ``cmd.exe`` lets the .cmd shim run normally.
    {
      name: "jarvis-dashboard",
      script: "cmd",
      args: "/c pnpm run start",
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
