# CROSS_SIGNAL Advisory Feed (amo-arbitrage → jarvis-trader) — Design Spec

**Date:** 2026-07-09
**Author:** Amo + Claude
**Status:** Approved design (conversational) — pending written-spec review
**Scope:** A small, read-only, advisory-only feed that surfaces amo-arbitrage's ML signals inside jarvis-trader's existing session brief. Not a coordination bus, not a trade gate.

---

## Background

This work was gated on the JARVIS v2 identity audit (2026-07-08), which confirmed jarvis-trader (port 8010) is a pure trading system with no ERP accretion — clearing the way to design cross-system coordination without an airgap-remediation prerequisite. Full manifest: `jarvis-v2-identity-manifest.md` (repo root, untracked).

Once that gate cleared, the open question was what "CROSS_SIGNAL / event_router" coordination actually means. Working through it interactively:

- **Systems in scope:** jarvis-trader and amo-arbitrage. jarvis-quant is explicitly **excluded** — investigation found it's a non-production IB API tutorial sandbox (its own README: "Throwaway learning sandbox... Not production," 6 files, 3 commits), not a real participant. Its shared-paper-account risk (`DUP662235`) is a separate cleanup, not a CROSS_SIGNAL concern.
- **What's driving it:** roughly equally position-conflict avoidance and signal-sharing — but investigation found **both accounts have essentially zero symbol overlap today**: jarvis-trader trades MES (S&P e-mini) and MGC (micro gold) only; amo-arbitrage trades 11 agricultural commodities. Position-conflict avoidance is close to moot at the current instrument set.
- **Gate vs. advisory:** advisory only. amo-arbitrage's signals must never influence a jarvis-trader trade/risk/fund decision.
- **Given the thin overlap, why build anything now?** Because a *small* advisory feed is cheap to build, costs nothing when overlap is zero (it just shows an informational, ignorable panel), and establishes the integration pattern for if/when instrument overlap grows (e.g. jarvis-trader adding MCL — crude oil — would start to approach amo-arbitrage's commodity space). A full coordination bus would be over-building for today's actual need. This scoped-down version is the recommended approach and what this spec covers.

## Goal

Add amo-arbitrage's latest ML signals (`ic_overall`, `win_rate_oos`, `prob_up` per symbol) as a clearly-labeled, non-authoritative section of jarvis-trader's `GET /brief/session` response — so Amo can see both systems' signal state in one place without either system depending on or gating the other.

## Non-goals

- Does **not** feed jarvis-trader's trade/risk/fund decision logic in any way. Advisory display only.
- Does **not** gate, veto, block, or delay any jarvis-trader action.
- Does **not** write to amo-arbitrage, and requires **no change on the amo-arbitrage side** — it consumes the existing unauthenticated `GET /api/signals/ml` endpoint as-is.
- Does **not** touch jarvis-quant (excluded from scope, see Background).
- Does **not** replace or feed into the `social_analyst.py` sentiment pipeline — that pipeline's Corey-Discord-only gate (`social_analyst.py:347-356`) is deliberately untouched; this is a separate, clearly-distinguished data source.
- Does **not** run as its own polling loop inside the engine. It fetches live on each `/brief/session` call, matching the router's existing pattern (`_collect_snapshots` also reads fresh on each call). A *separate*, already-shipped infra concern — the `amoarb-signal-bridge-watch` scheduled loop — independently watches the same amo-arbitrage endpoint for staleness/reachability so a dead upstream is caught before anyone hits `/brief/session` and wonders why the section is empty.
- Does **not** attempt position-conflict detection in this iteration — instrument overlap is currently zero, so there is nothing to detect. Revisit if/when jarvis-trader adds an instrument that overlaps amo-arbitrage's commodity set.

## Existing infrastructure leveraged

| Component | Status | Role in new design |
|---|---|---|
| amo-arbitrage `GET /api/signals/ml` (`backend/routers/signals.py`) | Production, unauthenticated GET | Data source — returns latest 100 rows (`symbol, signal, prob_up, ic_overall, win_rate_oos, signal_date`), no changes needed |
| jarvis-trader `GET /brief/session` (`engine/routers/session_brief_router.py`) | Production (Phase 5) | Host surface — gains one new optional section |
| `engine/analytics/session_brief.py` `build_session_brief()` | Production, pure function | Stays pure (no I/O); gains one new optional parameter to render pre-fetched advisory data |
| `amoarb-signal-bridge-watch` loop (`~/.claude/loops/amoarb-signal-bridge-watch/`) | Deployed 2026-07-09 | Independent staleness/reachability watchdog on the same endpoint — not part of the request path, just an early-warning signal to Amo |

## Architecture

```
[amo-arbitrage :8000]  GET /api/signals/ml
        │  (async, 5s timeout, never raises)
        ▼
engine/integrations/amoarb_signals.py :: fetch_amoarb_signals()
        │  returns {available, signals[], error, fetched_at} — always, never throws
        ▼
engine/routers/session_brief_router.py :: get_session_brief()
        │  awaits fetch_amoarb_signals() alongside the existing _collect_snapshots()
        ▼
engine/analytics/session_brief.py :: build_session_brief(snapshots, cross_signals=...)
        │  PURE — formats what it's handed, does no I/O itself
        ▼
{ generated_at, actions: [...existing...], cross_signal_advisories: {...new...}, count, degraded, note }
```

Two options were considered:

### Option A — New integration module + optional session_brief param (selected)

A new `engine/integrations/amoarb_signals.py` does the HTTP call (async, timeout, graceful degrade — per `engine-python.md`'s "async with graceful fallback" convention already used for every other external call). The router fetches it and passes the result into `build_session_brief()` as a new optional keyword argument. `session_brief.py` stays a pure formatter — it never does I/O, matching its own documented invariant ("Pure module: no engine imports, no I/O, deterministic when a fixed `now` is supplied").

**Pros:** Keeps the existing pure/I/O boundary intact; default parameter means zero behavior change for any caller that doesn't pass `cross_signals`; new code is additive and isolated to one new file + two small edits.
**Cons:** One more field for API consumers (the dashboard) to eventually decide whether to render — acceptable, since it's clearly namespaced and optional.

### Option B — Fold the fetch into `_collect_snapshots` (rejected)

Fetch amo-arbitrage signals directly inside the router's existing snapshot-collection helper and merge into the same `actions` list shape.

**Why rejected:** Would make amo-arbitrage signals indistinguishable from jarvis-trader's own pipeline-derived recommendations in the response shape — directly contradicts the advisory-only, non-authoritative requirement. Keeping it a separate top-level key is what makes "this is FYI, not a decision" visually and structurally obvious to any consumer.

## Components

**`engine/integrations/amoarb_signals.py` (new)**
```python
AMOARB_SIGNALS_URL = os.environ.get("AMOARB_SIGNALS_URL", "http://127.0.0.1:8000/api/signals/ml")
AMOARB_SIGNALS_TIMEOUT_S = 5.0

async def fetch_amoarb_signals() -> dict:
    """Never raises. Returns:
    {available: bool, signals: list[dict], error: str | None, fetched_at: iso-str}
    """
```
New `integrations/` package — this is the first cross-repo integration jarvis-trader has, so it gets its own directory rather than being wedged into an existing one (`data/`, `brokers/` etc. are all same-domain, this is deliberately a different kind of dependency).

**`engine/analytics/session_brief.py` (edit)**
`build_session_brief(snapshots, *, cross_signals: Optional[dict] = None, ...)`. When `cross_signals` is `None` (the default — every existing caller), behavior and output shape are byte-identical to today. When provided, adds a `cross_signal_advisories` key:
```python
{
    "source": "amo-arbitrage",
    "available": bool,
    "signals": [...],       # only when available
    "note": str | None,     # honest gap statement when unavailable, same philosophy as `why`
}
```

**`engine/routers/session_brief_router.py` (edit)**
`get_session_brief()` additionally awaits `fetch_amoarb_signals()` and passes the result through. Both fetches (`_collect_snapshots`, `fetch_amoarb_signals`) are independent and either can fail without affecting the other — a dead amo-arbitrage endpoint degrades only the new section, never breaks the existing brief.

## Data flow

1. Client calls `GET /brief/session`.
2. Router awaits `_collect_snapshots()` (existing, DB-backed) and `fetch_amoarb_signals()` (new, HTTP) — independently, so one failing doesn't block the other.
3. Router calls `build_session_brief(snapshots, cross_signals=amoarb_result)`.
4. Pure formatter assembles the existing `actions` list unchanged, plus the new `cross_signal_advisories` block from whatever `fetch_amoarb_signals()` returned.
5. Response returned as today, with one additive key.

## Error handling

Matches the module's existing "never fabricate" philosophy end to end:
- `fetch_amoarb_signals()` catches connection errors, timeouts, and non-200/malformed responses internally — never raises, never lets a dead amo-arbitrage take down `/brief/session`.
- When unavailable, `cross_signal_advisories.available = False` with a plain-English `note` (e.g. "amo-arbitrage signal feed unreachable — not fabricating signal data"), mirroring how `build_action()` already handles a reasoning-less snapshot.
- No retries inside the request path — a single 5s-timeout attempt per call. Retobustness against a *persistently* down endpoint is the separate `amoarb-signal-bridge-watch` loop's job (already deployed), not this code path's.

## Testing

- New `engine/tests/test_amoarb_signals.py`: happy path (mocked 200 + valid JSON), timeout, connection-refused, malformed JSON — asserts `fetch_amoarb_signals()` never raises in any case and returns the documented shape.
- Extend `engine/tests/test_session_brief.py`: assert `build_session_brief(snapshots)` (no `cross_signals` arg) is unchanged from current passing tests (backward compatibility); add cases for `cross_signals={"available": True, ...}` and `{"available": False, ...}` asserting the new key's shape.
- No integration test against a live amo-arbitrage instance — mocking is sufficient and keeps engine tests independent of a second repo being up.

## Rollout

Single PR, additive only, no config/env changes required beyond the optional `AMOARB_SIGNALS_URL` override (defaults to the existing local port 8000). No `[safety-review]` tag needed — touches no file under `engine/risk/`, `engine/config.py`, or execution/kill-switch code. Ships behind nothing; it's safe by construction (advisory, optional-default, isolated I/O).
