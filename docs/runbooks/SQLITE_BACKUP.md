# SQLite database backup

**Risk:** [RISK-005](../strategic/05_RISK_REGISTER.md) — loss of `jarvis_trader.db` destroys paper history, approvals, and `system_state` (including kill-switch persistence).

## What ships in code

| Piece | Location |
|-------|----------|
| Backup implementation | [engine/backup/db_backup.py](../../engine/backup/db_backup.py) |
| Nightly job | [engine/main.py](../../engine/main.py) — APScheduler **23:30 UTC** (`nightly_db_backup`) |
| Status | `GET /health/backup-status` |
| On-demand | `POST /health/backup-now` (authenticated like other engine routes) |
| Extended status | `GET /system/backup-status` |

**Default paths (relative to `engine/` working directory):**

- Live DB: `data/jarvis_trader.db`
- Backups: `data/backups/` — timestamped files, **30-day retention** by default

## Operator checklist

- [ ] After first deploy, call `GET /health/backup-status` and confirm backups directory is populated within 24h (or run `POST /health/backup-now` once).
- [ ] Monthly: confirm oldest backup age matches retention policy.
- [ ] Before OS reinstall or disk migration: copy `data/backups/` **and** `data/jarvis_trader.db` off-box.

## Tests

- [engine/tests/test_db_backup.py](../../engine/tests/test_db_backup.py)

## If backup init failed on startup

Engine logs: `Database backup init failed (non-fatal)`. Fix path permissions or disk space, then restart engine; use `POST /health/backup-now` to validate.
