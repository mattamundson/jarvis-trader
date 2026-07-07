# Deprecated Documentation

Documents in this directory are historical references only. They may contain outdated information (wrong ports, stale instrument status, superseded architecture). Always consult `docs/CURRENT_STATE.md` for the canonical system state.

## What's Here

- Session logs and transcripts from development phases
- Old architectural sketches and exploration notes
- Superseded analysis and debugging reports
- Historical test results and validation logs

## How to Use This Archive

1. **Never treat archived docs as source of truth** — they may conflict with current implementation
2. **Cross-reference with CURRENT_STATE.md** — that document is the canonical state
3. **Use archives only for historical context** — e.g., "how did we approach this problem in February?"
4. **When in doubt, trust the code** — active Python and TypeScript files in `engine/` and `dashboard/` are the source of truth

## Example Hazards

- **Ports**: Old docs may reference port 7497 (old TWS port), 3000 (old dashboard), or other stale values. See `CURRENT_STATE.md` for the active ports.
- **Instrument Status**: Archived session logs may claim MES or MGC are tradeable. Check `CURRENT_STATE.md` for current approval status.
- **Architecture**: Old pipeline or orchestrator designs may have been superseded. Refer to active `engine/agents/pipeline.py` and `engine/markets/orchestrator.py`.

---

Last updated: 2026-04-02
