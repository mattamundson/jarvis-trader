# EXAMPLE — Overnight Report (worked reference, not a real run)

> This is a worked example of what the `/overnight` cloud Routine writes each
> night to `docs/loop-reports/YYYY-MM-DD-overnight.md`. The underscore prefix keeps
> it out of the dated-report namespace so it is never mistaken for an actual run.
> It was produced by a read-only dry run of the `/overnight` logic
> (`.claude/commands/overnight.md`) against this repo with the engine offline — so
> it also demonstrates the **DEGRADED** (engine-down) path. See
> `docs/runbooks/OVERNIGHT_ROUTINE_RUNBOOK.md` for setup.

## How this dry run was produced

Each phase below was executed read-only (no orders, no safety-file edits, no PR
opened, no heartbeat written). On a real night the engine is reachable and Phases 1
and 3 fill in live data instead of reporting "stale/skipped".

### Phase 0 — Brakes preflight
- Branch check: on a `claude/`-prefixed branch (passes; refuses `master`/`main`).
- Engine health probe `curl -s --max-time 3 http://localhost:8010/health`:
  **unreachable** → Phases 1 & 3 degrade to "engine down"; it does NOT try to start
  the engine.
- Circuit breaker armed (same tool+args 3x = halt); budget = Haiku-tier triage.

### Phase 1 — Monitoring + brief (static portion ran; runtime degraded)
`safety-reviewer` static check of `engine/config.py` — all hardcoded limits intact:

| Constant | Value | Invariant | Status |
|---|---|---|---|
| `LIVE_TRADING_ENABLED` | `False` | must be False | OK |
| `REQUIRE_HUMAN_APPROVAL` | `True` | must be True | OK |
| `AUTONOMOUS_AUTO_APPROVE_PAPER` | `False` | never auto-approve live | OK |
| `MAX_DAILY_LOSS_PCT` | `0.02` | -2% halt | OK |
| `MAX_DAILY_LOSS_USD` | `100.0` | $100 flat halt | OK |
| `MAX_DRAWDOWN_PCT` | `0.10` (code default; `.env` overrides higher in paper) | drawdown halt | OK |
| `MAX_POSITION_SIZE_PCT` | `0.05` | 5% cap | OK |
| `MAX_SINGLE_ORDER_VALUE` | `5000.0` | $5k cap | OK |
| `MAX_MARGIN_UTILIZATION` | `0.40` | 40% cap | OK |
| `MAX_ORDERS_PER_MINUTE` | `10` | rate throttle | OK |
| `MAX_CONTRACTS_PER_INSTRUMENT` | hard cap 20 (validator-clamped) | <=20 | OK |
| `MAX_OVERNIGHT_CONTRACTS` | `1` | <=1 overnight | OK |
| `MAX_CORRELATED_EXPOSURE_PCT` | `0.20` | 20% correlated | OK |

`pipeline-debugger` (last 3 runs) and `backtest-runner` (WFE snapshot): **stale** —
both need the live engine; reported as stale, never fabricated.

### Phase 2 — Dev triage
- `ruff check . --config ruff.toml` → All checks passed.
- pytest fast suite + `pnpm run build` → run in the Routine's cloud env (deps present).
- No safe autonomous fixes pending → no draft PR opened this run (correct: a draft PR
  is opened only when there is something to commit).

### Phase 4 — Report + heartbeat
- `.heartbeat`: first run creates it.
- Consolidated report below.

---

## The consolidated report (what lands in your inbox)

```markdown
# Overnight Report — 2026-06-27

**Verdict:** DEGRADED  (engine unreachable — monitoring/research could not run live)

## Run metadata
- UTC 01:4x  /  CT 20:4x (prev day)
- Branch: claude/overnight-execution-uin1y0
- Model/cost: Haiku (triage) — well under budget
- Phases: 0 OK | 1 partial (safety static OK, pipeline/WFE stale) | 2 OK (ruff clean)
  | 3 skipped (engine down) | 4 OK

## Monitoring & Morning Brief
- Engine: DOWN (no listener on 8010) — restart needed before session
- Safety limits: all 13 hardcoded caps intact, kill-switch config unchanged
- Kill switch / loss tracker / equity / positions: UNAVAILABLE (engine down)
- Per-symbol go/no-go: N/A until engine up

## Dev Triage
- ruff: clean. pytest/dashboard: deferred to live env. No changes -> no draft PR.

## Research / Backtest
- Skipped (engine down). WFE/MCPT/last30days require live endpoints.

## Blocked / needs-human ([safety-review])
- None. (Engine-down is operational, not a safety-review item.)
```

---

## What a healthy (engine-up) night adds

When the engine is reachable (real cloud Routine or local with the engine on), the
empty/stale sections fill in: live kill-switch + loss-tracker state, equity
current/peak, open positions, per-symbol GO/NO-GO, the last 3 pipeline verdicts, the
WFE snapshot vs thresholds, the research/backtest sweep results, and — if Phase 2
found safe fixes — a link to the `[overnight]` draft PR. The verdict then reads
`GO` or `NO-GO` instead of `DEGRADED`.
