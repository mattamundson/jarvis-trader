# Decision Memo — Gate v2 Phase 3-FULL Activation

**Status:** ACTIVE
**Activated:** 2026-04-21 17:11 CT
**Branch:** `feat/tradingview-mcp-gamma-kraken`
**Author:** Matt Morrison (with Claude Opus 4.7)
**Roadmap reference:** P0.4 in `docs/ROADMAP_2026-Q2-Q4.md`

---

## Context

Prior state: gate v2 was shipping in three progressive phases since mid-April. Phases 1 and 2 (commits `c8f4610`, `3198364`) delivered the dual-pathway validator, the weekly Saturday 01:00 CT APScheduler cron, and the VerdictSnapshot JSON persistence layer. Phase 3-LIGHT (`3198364`) added advisory readers to `engine/backtest/gate_v2_policy.py` that logged verdicts but did not gate any routing — a pure observability tier.

Phase 3-FULL (`33c9ff2`, 2026-04-21 ~16:50 CT) introduced `GATE_V2_ENFORCE_ROUTING` env-flagged hard enforcement in `generate_instrument_signals`. When the flag is `1`, any symbol without a fresh PASS verdict is force-overridden to `NO_TRADE`. The code shipped DORMANT with the env var defaulting to `0`.

The decision in this memo is whether to flip `GATE_V2_ENFORCE_ROUTING=1` in production.

The broader context: we have four futures families under routing (MES, MNQ, MCL, and a fourth slot). All four historically FAILED the proposed gate v2 bar (`pf_ci_lower>=1.10 AND p_edge>=0.95 AND mc_95th_dd<=5% AND dsr>=0.10`). MES rank 7 at 2/4 is the MARGINAL best. MCL and MNQ are already statically blocked in `DO_NOT_TRADE_SYMBOLS`. Without Phase 3-FULL, any future unblock of MCL/MNQ would have to pass human review; with Phase 3-FULL, the fail-safe deny becomes the system default.

## Decision

**Activated `GATE_V2_ENFORCE_ROUTING=1` in `engine/.env` Section 11** at 2026-04-21 17:11 CT. Engine was pm2-restarted and smoke-verified before closing the session.

Concretely: every symbol entering `generate_instrument_signals` now has its verdict JSON read from `engine/data/gate_v2_verdicts/{SYMBOL}_{strategy}_rank{n}.json`. If the file is missing, stale (>14 days since `created_at`), or reports verdict ≠ PASS, the signal is rewritten to `entry_signal=NO_TRADE` and `exit_signal=NO_EXIT`. `DO_NOT_TRADE_SYMBOLS` retains precedence.

## Alternatives considered

**Stay Phase 3-LIGHT (advisory-only).** Safest. No risk of the gate over-blocking a profitable instrument. Rejected because the whole point of shipping the enforcement code was to move from "we have a gate" to "the gate gates." Leaving the flag off indefinitely would have been operational theater — statistical hygiene work that never actually constrained live routing.

**Hybrid soft-block with human override.** Route FAIL symbols to a secondary queue that requires WhatsApp approval. Rejected as Phase 4 work (approval surfaces); would also have dragged P0.4 into the Phase 4 window (2026-05-26+), blocking every downstream P1 strategy expansion on an item that could be shipped today.

**Wait until all four strategies pass gate v2.** Rejected because (a) MCL and MNQ are already static-blocked and won't be unblocked without a per-symbol WFO winner anyway, and (b) MES rank 7 PASS is sufficient for the only symbol currently routing.

## Tradeoffs

**Gains:**
- Fail-safe default-deny: if the Saturday cron silently stalls, trading halts 14 days later rather than continuing against a stale edge. This is the load-bearing property.
- Auditable decision trail: every routing decision now has a JSON verdict file behind it, dated.
- Forcing function on the weekly cron: a stall will actually page operator attention (no MES trades for a day) rather than decay silently.

**Risks:**
- The 14-day staleness window is a single point of failure. If the cron stalls on 2026-04-25 and nobody notices, MES stops trading around 2026-05-09. Task 12 in the top-10 worklist covers weekly verdict-age monitoring.
- A false-positive FAIL from MBB CI variance could halt a still-edge-bearing strategy. Mitigation: MBB CI is the hardest of the four criteria; a single weekly re-score either PASSes or we accept the block as signal.
- Advisory→enforcement transition is irreversible in the sense that once operators rely on the gate, turning it back off means re-introducing a human checkpoint we just removed.

## Smoke-test evidence (pre-production)

Ran the Phase 3-FULL test suite before activation: 22 new enforcement tests green; 56 total gate v2 tests green end-to-end.

Live pre-activation smoke on the dev engine (GATE_V2_ENFORCE_ROUTING=1, restart, fire `/pipeline/run` for each symbol):
- SPY (out-of-scope: no gate v2 verdict exists for SPY) — 117 baseline entries in a dry run → 0 entries under enforcement. Confirms fail-safe default-deny.
- MES (PASS verdict fresh as of 2026-04-21) — signal generation passes through untouched. Confirms PASS path does not over-gate.
- MCL, MNQ — remain NO_TRADE via `DO_NOT_TRADE_SYMBOLS` (static block takes precedence, as designed).

Post-activation verification in production: `/health` green, `/pipeline/run` for MES returns the expected trend-rank-7 signal, `[GateV2Policy] eligible=True` log line present for MES.

## Rollback

If a rollback is needed (unexpected over-blocking, cron failure that cannot be repaired within one week, or any confidence-degrading surprise):

1. Edit `engine/.env` Section 11: change `GATE_V2_ENFORCE_ROUTING=1` → `GATE_V2_ENFORCE_ROUTING=0`
2. `.\restart_engine.ps1` (PM2 path auto-cycles the process with the new env)
3. Verify `/health` comes back green and a test `/pipeline/run` for MES returns a signal (no NO_TRADE override)

Time-to-rollback: under 3 minutes. The only state that persists is the verdict JSON files, which are advisory once the flag is off.

## Known failure modes

- **Cron stall.** APScheduler Saturday 01:00 CT job fails to fire for 14+ days → all routed symbols halt. Mitigation: Task 12 worklist polls `created_at` ages daily; alert if any symbol's verdict ages past 10 days without refresh.
- **PM2 no-op restart.** Historically observed (see `restart_engine.ps1` PM2 fast path); the uptime-verification regex catches this and aborts. The script exits 1 if pm_uptime > 60000ms post-restart.
- **Verdict JSON corruption.** Fail-safe: the policy reader treats a JSON parse error as a non-PASS verdict, blocking the symbol. Prefer blocking over trading on corrupt state.

## Links

- Roadmap row D1 (decision point): `docs/ROADMAP_2026-Q2-Q4.md` — resolved 2026-04-21
- Gate v2 proposal and Tier A validation memo: `C:\Users\mattm\.claude\projects\C--windows-system32\memory\project_gate_v2_proposal.md`
- Commits: `c8f4610` (Phase 1) · `3198364` (Phase 2 + 3-LIGHT) · `33c9ff2` (Phase 3-FULL)
- Saturday cron next fire: 2026-04-25 01:00 CT (first production run, monitored under Task 12)
