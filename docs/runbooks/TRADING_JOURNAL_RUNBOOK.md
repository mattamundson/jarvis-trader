# Trading Journal Runbook

**Component:** `engine/journal/` + `scripts/generate_trading_journal.py`
**Status:** Implemented, cron OFF by default
**Owner:** Matt (Amo)
**Last updated:** 2026-05-21

---

## What It Generates

A single Markdown file per trading day, vault-ingestible via gbrain, containing:

| Section | Source |
|---------|--------|
| **At a Glance** | `pnl_snapshots` + `paper_trades` computed stats |
| **Trades** | All closed `paper_trades` where `date(exit_time) == target_date` |
| **P&L Snapshot** | `pnl_snapshots` for the date (daily_pnl, equity, peak, DD%) |
| **Corey Commentary Highlights** | Top 5 substantive messages (>=200 chars) from `discord_corey_commentary` |
| **Bot Signal Summary** | Count by symbol + direction from `discord_bot_signals` |
| **JARVIS Queries** | Intent histogram from `engine/logs/jarvis_ask.log` |
| **Notes** | Kill-switch events, large drawdowns, anomalies |

**Output path:**
```
~/master-jarvis/second-brain/raw/_session-journal/<YYYY-MM-DD>.md
```

**Frontmatter** (gbrain-ingestible):
```yaml
---
source: "trading-journal"
kind: "daily-journal"
date: "2026-05-20"
trade_count: 3
daily_pnl_usd: 90.0
win_rate: 0.6667
tags:
  - trading-journal
  - daily
  - jarvis-trader/audit-trail
---
```

---

## Sample Output (first ~15 lines of entry body)

```markdown
# Trading Journal — 2026-05-20

_Generated: 2026-05-21T00:12:34.567890+00:00_

---

## At a Glance

| Metric | Value |
|--------|-------|
| Daily P&L | $+90.00 |
| Trades closed | 3 |
| Wins / Losses | 2 / 1 |
| Win rate | 66.7% |
| Regime call | bull |
```

---

## Running Manually

```powershell
# Dry run — print output to console, no file written
engine\.venv\Scripts\python scripts\generate_trading_journal.py --date 2026-05-20 --dry-run

# Write for a specific date
engine\.venv\Scripts\python scripts\generate_trading_journal.py --date 2026-05-20

# Write to a custom output directory (must be the vault ROOT, not the _session-journal subdir)
engine\.venv\Scripts\python scripts\generate_trading_journal.py --date 2026-05-20 `
    --output-dir C:\Users\mattm\master-jarvis\second-brain\raw

# Default date = yesterday (post-close write-up pattern)
engine\.venv\Scripts\python scripts\generate_trading_journal.py
```

All runs are **idempotent** — running twice on the same date overwrites the entry with a new `_Generated:` timestamp. The file content (trades, snapshots, commentary) is always a fresh pull from the DB.

---

## How to Enable the Daily Cron

The cron is **OFF by default**. To activate the 5 PM CT weekday automation:

```powershell
# Register the task (idempotent — safe to run more than once)
.\scripts\register_journal_cron.ps1

# Verify
schtasks /Query /TN "Jarvis-TradingJournal-Daily" /V /FO LIST
```

The task runs at **23:00 UTC (5 PM CST / 6 PM CDT)** every weekday using the engine venv Python directly (`engine\.venv\Scripts\python.exe`).

### Pre-conditions

- `engine\.venv\Scripts\python.exe` must exist
- `scripts\generate_trading_journal.py` must exist
- The vault root `~/master-jarvis/second-brain/raw/` must exist (or pass `--output-dir`)

---

## How to Disable the Cron

```powershell
# Soft disable (task stays registered, won't run)
schtasks /Change /TN "Jarvis-TradingJournal-Daily" /Disable

# Re-enable
schtasks /Change /TN "Jarvis-TradingJournal-Daily" /Enable

# Permanent removal
schtasks /Delete /TN "Jarvis-TradingJournal-Daily" /F
```

---

## Idempotency Guarantee

- **Same date, run twice:** overwrites the file. Only the `_Generated:` timestamp changes.
- **Empty day (no trades, no snapshots):** generates a valid entry with zero counts in frontmatter. All sections render with "_No data_" placeholders. Frontmatter is still valid YAML — gbrain ingests it without error.
- **Missing jarvis_ask.log:** silently skipped. JARVIS Queries section renders as "_No /jarvis/ask requests recorded._"
- **Missing commentary / signals:** each section renders its own "no data" placeholder.

---

## Data Sources (All Read-Only)

| Source | Access | Columns Used |
|--------|--------|--------------|
| `paper_trades` | SQLite SELECT | trade_id, symbol, side, quantity, entry/exit_price/time, pnl, regime |
| `pnl_snapshots` | SQLite SELECT | daily_pnl, portfolio_equity, peak_equity, consecutive_losses |
| `discord_corey_commentary` | SQLite SELECT | timestamp, content, channel |
| `discord_bot_signals` | SQLite SELECT | timestamp, symbol, direction |
| `alert_log` | SQLite SELECT | alert_type, message, created_at |
| `system_state` | SQLite SELECT | kill_switch_active, kill_switch_reason |
| `jarvis_ask.log` | File read (JSONL) | timestamp, intent |

No writes to any source table. No engine restart required.

---

## Architecture

```
scripts/generate_trading_journal.py   ← CLI entrypoint
    └── engine/journal/__init__.py    ← public API re-exports
        └── engine/journal/builder.py ← all data + rendering logic
```

**Importable library API:**
```python
from engine.journal import build_journal_entry, render_markdown, write_to_vault

entry = build_journal_entry(
    target_date=date(2026, 5, 20),
    db_path="engine/data/jarvis_trader.db",
    log_path="engine/logs/jarvis_ask.log",   # optional
)
md = render_markdown(entry)
path = write_to_vault(entry, "~/master-jarvis/second-brain/raw")
```

---

## Tests

```powershell
engine\.venv\Scripts\python -m pytest engine/tests/test_trading_journal.py -v
```

6 tests covering: empty day, full day, idempotent overwrite, frontmatter shape, JSONL log parsing, kill-switch surfacing.

---

## Phase 3 Readiness — Why This Matters

The journal directly feeds the most critical Phase 3 blocker: **C2 — `paper_trades_count` >= 100 closed trades**.

Each journal entry records the day's closed trade count and daily P&L in its frontmatter. Over 60 days of entries, the gbrain vault accumulates a machine-readable audit trail where:

- `trade_count` per entry → progress toward the 100-trade C2 threshold
- `win_rate` per entry → rolling view of the C3 (55% win rate) criterion
- `daily_pnl_usd` per entry → input to the C4 (profit factor) and C6 (Sortino) calculations
- Kill-switch events surfaced in Notes → direct input to C8 (`kill_switch_invocations <= 2`)

This is the **paper-to-live audit trail** that Phase 3 requires before any live capital deployment. The journal is how you *prove* the strategy has been running consistently — not just that the code says it has.

See `docs/runbooks/PHASE3_READINESS_CRITERIA.md` for the full 10-criterion checklist.

Cross-link: `[[STARK_MODE_OPERATING_PHILOSOPHY]]`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Database not found` | Wrong cwd or `--db` path | Run from project root; use absolute `--db` path |
| Empty Trades section | No `status='closed'` exits on that date | Normal for non-trading days |
| Empty Commentary | No messages >= 200 chars | Check `discord_corey_commentary` for that date |
| Vault dir not found | `~/master-jarvis/second-brain/raw` missing | Pass `--output-dir <existing-path>` |
| Task not running | Cron registered but disabled | `schtasks /Change /TN "Jarvis-TradingJournal-Daily" /Enable` |
| Old entry not overwritten | File-system permissions | Check vault dir permissions; run as same user as the task |
