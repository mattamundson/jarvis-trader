# AF-1 — Session Flatten Time Intent

**Decision date:** 2026-04-22
**Resolves:** Roadmap AF-1 (Q2-P2.9)
**Status:** NOT A BUG — closing flag

## Finding

The deployment-verification-agent's run on 2026-04-22 PM flagged a potential inconsistency between:

- A claimed "15:00 CT overnight cutoff" somewhere in the trade/risk layer
- The constant `SESSION_FLATTEN_TIME_ET = "15:45"` (= 14:45 CT) found in code

## Ground-truth grep

Only relevant matches across `engine/`:

| File | Line | Content | Meaning |
|---|---|---|---|
| `engine/config.py` | 184 | `SESSION_FLATTEN_TIME_ET: str = "15:45"  # Flatten all positions at 3:45 PM ET` | The actual flatten trigger |
| `engine/schedulers/eod_scheduler.py` | 601-622 | `async def run_session_flatten(self) -> None` | Handler that calls `tracker.flatten_all_positions()` |
| `engine/schedulers/eod_scheduler.py` | 710-722 | APScheduler `cron: Mon-Fri 20:45 UTC` id=`session_flatten` | 20:45 UTC = 15:45 ET = 14:45 CT ✓ consistent |
| `engine/database/migrations.py` | 949 | `close_price  REAL, -- CT 15:00 close (filled by outcome job)` | A **schema-column comment** describing NYSE equity-index cash close (16:00 ET = 15:00 CT) |

No "15:00 CT cutoff" exists as a trade-gating constant. The agent conflated the `close_price` schema-column comment with a flatten time.

## Decision

The **intentional** flatten time is **14:45 CT (15:45 ET)**:

- 15 minute buffer before the NYSE equity-index cash close at 16:00 ET / 15:00 CT
- Avoids trying to flatten during the final-minute liquidity crunch when the S&P closing print is volatile
- CME Globex MES continues trading after this; the flatten is an operational choice to realize P&L against the RTH session-close benchmark, not a hard market constraint

## Action

**None.** AF-1 closed as non-issue. Roadmap task Q2-P2.9 demoted from "action required" to "documented."

## References

- `engine/config.py:184`
- `engine/schedulers/eod_scheduler.py:601-722`
- `engine/database/migrations.py:949` (source of the agent's false-positive)
- Parent: `docs/ROADMAP_2026-Q2-Q4.md` section 0.2
