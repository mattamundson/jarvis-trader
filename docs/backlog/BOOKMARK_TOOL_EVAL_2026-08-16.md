# Bookmark Tool Eval — Vibe-Trading & LACP

> Follow-on to the 2026-08-16 vault review of the 50-tool bookmark batch (all captured
> 2026-05-29, backfilled into gbrain 2026-08-03, never acted on).
> Scope: the two items that carried a `verdict: install` and the strongest repeat-signal.
> Last updated: 2026-08-16

## Verification level

**Documentation read only.** Both repos were evaluated by reading their public READMEs and
comparing the claimed capabilities against this repo's actual module tree. Neither repo was
cloned, installed, or executed. No claim below is "tested" — the overlap findings are
`read-and-compared`, not `ran and observed`. Any item promoted out of this backlog needs its
own runtime verification before it can be called done.

The gbrain daemon (`:8077`) was not reachable from the environment this eval ran in, so vault
state is quoted from the prior session, not re-confirmed here.

## Item 1 — Vibe-Trading (HKUDS)

<https://github.com/HKUDS/Vibe-Trading> — MIT, ~31k stars, ~4,700 tests, actively maintained.

**Bookmarked 5x** — the highest repeat-signal of any item in either cluster.

### What it actually is

A complete AI trading platform: FastAPI backend + React frontend + tool-based agent loop +
multi-market backtest engine + 10 broker connectors + MCP server. That is structurally the
*same shape as jarvis-trader*, not a component of it.

| Vibe-Trading | jarvis-trader equivalent |
|---|---|
| FastAPI backend, agent loop | `engine/` + 10-agent pipeline |
| React frontend | `dashboard/` (Next.js) |
| Backtest engine, 9 markets | `engine/backtest/` (MES-specific, gate-v2 / CPCV / MCPT) |
| 10 broker connectors | `engine/brokers/` (IB only, deliberately) |
| Persistent memory | gbrain second-brain |

### Verdict: do not adopt wholesale

The 5x bookmark signal reflects "this is impressive," not "this fits." Adopting it means
replacing jarvis-trader, which means discarding the parts that are actually this project's
differentiator: `engine/risk/safety_layer.py`, the hardcoded kill switch, gate-v2, the DSR
honest-data-drain correction, and the point-in-time discipline in `.claude/rules/testing.md`.
A general-purpose platform with 9 markets and 10 brokers has no reason to carry any of that.

### Safety flag — read before installing anything

Vibe-Trading **places real orders**, and Interactive Brokers is one of its connectors.
Installing it on the same machine as jarvis-trader would create a **second, independent order
path to IB Gateway that does not pass through `SafetyLayer`** — bypassing all six risk checks,
the -8% daily / -20% drawdown kill switch, and the permanent block on port 4001. Its own
mandate-gate and kill-switch are *its* safeguards, not ours, and they know nothing about our
position state or loss tracker.

If this is ever trialled, it must be on an isolated machine or in a container with no route to
port 4002/4001, with its broker connectors unconfigured. This is a Tier-3 decision, not a
casual `git clone`.

### Extractable without adopting the platform

| Piece | Value | Notes |
|---|---|---|
| 456-factor academic library | Medium-high | `engine/analytics/` has ~40 hand-built signal modules. A vetted factor library is purely additive, touches no safety code, and feeds `ic_ensemble.py`. Best single reason to read the source. |
| MCP server exposing trading tools | Medium | jarvis-trader has no MCP server over its own engine. Worth reading the tool-schema design. |
| Broker connectors | **None** | Anti-goal. Paper-only IB is a deliberate constraint, not a missing feature. |
| Backtest engine | Low | Ours is deeper for futures specifically (bar permutation, CPCV, gate-v2, DSR). |

**Next action:** read the factor library's source and licensing, extract as a standalone
additive module behind a feature flag. Do **not** install the platform.

## Item 2 — LACP (0xNyk/lacp)

<https://github.com/0xNyk/lacp> — MIT, ~299 stars, Bash + Python 3, v0.6.0 released.
"Control-plane-grade agent harness for Claude, Codex & Hermes."

This is the better fit of the two, and it maps onto a documented failure in this repo.

### Overlap with what we already run

| LACP mechanism | jarvis-trader state |
|---|---|
| `pretool_guard.py` — blocks dangerous ops | **Covered** — `.claude/hooks/pre-tool-use/guard-trading-files.py` |
| `session_start.py` — git context injection | **Covered** — `check-port-8010.sh`, `verify-env.sh` |
| 5-layer memory / Obsidian + MCP | **Covered** — gbrain (3,311 pages, 100% embed coverage) |
| Risk tiers `safe`/`review`/`critical` | **Partial** — Tier-3 language exists in `.claude/rules/safety.md` but is prose, not a mechanized gate |
| `stop_quality_gate.py` — 3-tier eval incl. **LLM rationalization detection** | **GAP** — our stop hook is `session-log.sh`, which only logs |

### The gap worth closing

`stop_quality_gate.py` detects an agent rationalizing an unverified completion claim. That is
*exactly* the PR #280 incident already written into `CLAUDE.md`: an agent ran `tsc --noEmit`,
watched a Vercel deploy go green, and reported the fix "verified, and shipped" without ever
exercising the proxy. The rule exists in prose; nothing mechanically enforces it.

A stop-hook quality gate is the natural enforcement point:

- Small, local, Python — same shape as the existing hooks.
- Touches **nothing** in `engine/risk/`, `engine/config.py`, or kill-switch code. No
  `[safety-review]` tag required.
- Verifiable goal: a hook that, given a transcript ending in "verified / works / done / fixed"
  with no test-execution or runtime-observation tool call in the session, emits a warning
  naming the missing evidence. Known-input → expected-output test, not a build check.

**Next action:** read `stop_quality_gate.py` and `write_validate.py` for technique, then write
our own against the PR #280 case as the fixture. Do not install the 60-command LACP CLI — we
need one hook, not a control plane. Needs Matt's sign-off first: a stop hook changes session
behavior for every future run.

## Remaining cluster items (unchanged from the 08-16 gap pass)

| Item | Verdict | Effort | Action |
|---|---|---|---|
| **LLMLingua** (Microsoft, prompt/KV compression) | Real scoped gap | S/M | gbrain recall snippets enter context uncompressed via the `UserPromptSubmit` hook and `recall-graph.ps1`. Independently re-surfaced in `implement_from_bookmarks_2026-08-09` #19. Bounded change, no safety surface. |
| **mcp-memory-service** | Steal one mechanism | M | Autonomous consolidation (merging/pruning redundant memories) is the one thing gbrain lacks. Do not swap memory backends. |
| **reasoning-bank** (Google Research) | Narrower than it looks | M | Partially covered by `feedback_*` memories + session-optimizer. Check that skill's pattern-library health *before* building anything. |
| **agentmemory** | **Verify first** | S | Confirm whether gbrain's MCP server already reaches Codex CLI and Hermes. If yes, redundant. |
| **My-Brain-Is-Full-Crew** | Skim only | — | Would compete with a healthy pipeline (brain score 84). Email-triage skill is the only non-duplicated piece. |
| **timesfm** (Google) | Defer | M | Flag for a future forecasting-accuracy pass, not urgent. |
| qlib, pybroker, TradingAgents, hftbacktest, quant-trading, QuantMuse, tradetally, helix-db, Memento-Skills, mate, nyno | No action | — | Original `watch`/`review` triage was correct. Re-surface only on specific need. |

## Recommended order

1. **LACP stop quality gate** — closes a documented incident, no safety surface, smallest blast radius. Needs sign-off (changes session behavior).
2. **agentmemory verify** — pure investigation, might close itself out for free.
3. **LLMLingua compression** on the gbrain recall path — real, bounded, measurable.
4. **Vibe-Trading factor library** — read-and-extract only, platform stays uninstalled.

Everything else stays parked.
