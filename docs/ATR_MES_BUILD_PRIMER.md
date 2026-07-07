# Build Primer — Brief #1: Multi-Use ATR for MES (backtest-first, into gate v2)

> Source: `second-brain/IMPLEMENT_FROM_BOOKMARKS_2026-05-30.md`, rank #1.
> Purpose: turn ATR from a single-use stop into a multi-use toolkit on the live MES
> SMA trend strategy, validate through gate v2, promote NOTHING to live without Amo's
> explicit `[safety-review]` go. This file is the executable spec for a fresh session.

## How to run this (fresh session)

1. `/jarvis-trader`
2. Read this file, then `second-brain/IMPLEMENT_FROM_BOOKMARKS_2026-05-30.md` (the brief)
   and `docs/validation/STRATEGY_VALIDATION_2026-05-30.md` (the live-book verdict, if the
   strategy-validation-panel workflow has finished). Summarize the MES/MGC verdict + this
   spec before touching code.
3. Execute the phases below in order.

## Context — what exists today

- Live paper strategy: **MES — SMA trend, fast=60 slow=200, atr_trail_mult=2.0** (ALT gate v2
  PASS, Tier-3 authorized 2026-05-24). ATR is used ONLY as a trailing-stop multiplier today.
- The insight (Breakout Trading Academy bookmark): ~2/3 of ATR's utility is untapped —
  it can also drive profit targets and position sizing, not just stops.
- Canonical signal/param logic and config locations (CONFIRM these before editing — do not
  assume; locate the real files first):
  - `engine/backtest/signals.py` — canonical signal/threshold logic (Tier-3 to change)
  - `engine/backtest/paper_config.py` — enabled flags + per-symbol params
  - Engine venv: `engine/.venv/Scripts/python.exe` (never system Python)
- Gate v2 PASS bar: `pf_ci_lower >= 1.10`, `p_edge >= 0.95`, `mc_95th_dd <= 5%`
  (`<= 7%` ALT on $50k+), `dsr >= 0.10`. `GATE_V2_ENFORCE_ROUTING=1`. Missing/stale
  verdict => NO_TRADE (fail-safe). If gate v2 returns NO_TRADE, that IS the answer.

## Phase 1 — SPEC the three ATR variants (all config-flagged, default OFF)

Add three independently-toggleable ATR uses alongside the existing fixed 2.0x ATR stop:

- **(a) ATR trailing-stop that tightens with profit** — e.g. start at 2.0x ATR, ratchet to
  1.5x / 1.0x ATR as unrealized R grows. Param: tightening schedule.
- **(b) ATR vol-scaled profit targets** — target = `k * ATR` (test k ∈ {1.5, 2.0, 3.0}),
  optionally partial-scale-out. Param: target multiple(s).
- **(c) ATR regime-based position sizing** — size down when `ATR/price` (vol) is high, up when
  low, within existing max-contract caps. Param: vol bands → size multiplier. MUST respect the
  hardcoded position-size limits in `engine/config.py` (max 2 micro contracts, 5% portfolio,
  $5k single-order) — sizing variant may only ever size *down* from the cap, never up past it.

Each variant behind its own flag in `paper_config.py`, **default False**. The live MES book
must behave identically until a variant is explicitly promoted.

## Phase 2 — IMPLEMENT (sandbox/backtest path ONLY)

- Implement in the backtest path. Do NOT change the live MES runtime config, do NOT enable any
  flag, do NOT touch `engine/risk/**` or kill-switch code.
- Any edit to `signals.py`, `paper_config.py`, or `engine/config.py` carries the
  **`[safety-review]`** tag in the commit subject and ships DISABLED.
- Match existing code style; per-file staging only (never `git add -A` — the repo has unrelated
  uncommitted work). No push without Amo.
- Add/extend tests where the existing suite covers signal logic (`engine/tests/`); never modify
  `test_safety_layer.py` to make something pass.

## Phase 3 — BACKTEST each variant vs baseline

- Backtest each of (a), (b), (c) — and the most promising combinations — on ~2yr MES bars,
  against the current live SMA(60,200)+2.0x-ATR baseline.
- Use the backtest tooling already in the repo (locate the runner; the
  strategy-validation-panel recon step documents the exact invocation — reuse it).
- Run via the engine venv. Backtests are offline; do NOT disturb the live engine on port 8010,
  do NOT restart it, do NOT route any order.

## Phase 4 — GATE each variant through gate v2

- Run each variant through gate v2. PASS = all four thresholds above.
- A NO_TRADE / FAIL is a valid, useful result — it means do not deploy. Do not override.

## Phase 5 — VALIDATE the winner with the existing workflow (the loop closing on itself)

- For any variant that PASSES, validate it adversarially by reusing the workflow built
  2026-05-30: **`strategy-validation-panel`** (WFO stability / Monte-Carlo DD / cost-slippage /
  overfitting-DSR gauntlet + refute pass). Point it at the new variant rather than the live book.
- This is the elegant part: today's validation workflow validates tomorrow's strategy.

## Phase 6 — REPORT (decision-support only)

Produce a verdict table:

| Variant | PF CI lower | p_edge | MC-DD | DSR | Gate v2 | Adversarial panel | Recommend |
|---|---|---|---|---|---|---|---|

Plus a one-paragraph recommendation. **Promote NOTHING to live** — a PASS only earns a
"promote?" conversation, and even then it is Amo's `[safety-review]` decision.

## Definition of done

A verdict table telling Amo which (if any) ATR variant beats the baseline through gate v2 +
the adversarial panel. A clean FAIL is a successful outcome — it prevents deploying noise.
Live MES config remains untouched; all new code ships behind OFF-by-default flags.

## Hard guardrails (non-negotiable)

- `LIVE_TRADING_ENABLED = False`, `REQUIRE_HUMAN_APPROVAL = True` — invariants, never change.
- No live config change, no flag enabled, no engine restart, no IB/order routing, no `git push`.
- `[safety-review]` tag on any safety-file edit; gate v2 is the arbiter, not the LLM.
- Backtest-first, paper-only, promote-on-explicit-go-only.
