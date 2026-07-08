# Design: ES Auction / Overnight-Bias Card (dashboard)

Status: **DRAFT / scoping** — not implemented. Opened out of the 2026-07-08 ES EOD
analysis (`docs/reports/eod/2026-07-08-ES-eod-brief.md`), where a live TOS chart
drove a "line-in-the-sand" overnight-bias call by hand. This doc scopes building
that synthesis into the dashboard as an **advisory** card.

## Goal

A dashboard card that, for an active symbol (MES, MGC), renders a server-computed
auction read: the Saty ATR triggers/bias, the TPO profile target / fail-target, the
ingested Corey commentary bias, and a synthesized **line-in-the-sand** pivot with
its two outer confirmations — each carrying an honest provenance badge.

## Non-goals (explicit)

- **Not** a mirror of Matt's ThinkOrSwim chart. The `AA_CoreyTscorev2` and AA Saty
  overlays are thinkScript studies inside TOS (closed platform, no API). We render
  the engine's own re-derivation, clearly labeled `engine-derived, not chart-parity`.
- **No execution / routing.** Advisory decision-support only — `REQUIRE_HUMAN_APPROVAL`
  and no-LLM-in-safety stand. The card informs; it never places or sizes an order.
- **No streaming tick feed / live level-cross alerting** in v1 (see Phase 2).

## What already exists (reuse, do not rebuild)

| Piece | Location |
|---|---|
| Saty ATR levels / triggers / bias / nearest target | `engine/backtest/indicators.py` (`saty_atr_levels`, `saty_bias`, `saty_nearest_target`) |
| Saty screenshot-parity test | `engine/tests/test_saty_atr_levels.py::test_levels_match_live_screenshot` |
| TPO profile targets / fail-targets | `engine/backtest/tpo_profile.py` |
| Corey auction bias (Stage-1 agent) | `engine/agents/corey_auction_analyst.py` |
| Corey commentary feed endpoint + widget | `/corey-alerts` (`discord_router.py`), `dashboard/components/discord/corey-feed.tsx` |
| Institutional profile widget + endpoint | `/profile/{symbol}` (`institutional_router.py`), `dashboard/components/InstitutionalProfileWidget.tsx` |
| Price snapshot w/ derived provenance | `/prices/snapshot` (`routers/prices_router.py`, `data/provenance.py`) |
| Morning levels | `engine/analysis/morning_levels.py` |

The work is a **synthesis endpoint + one widget + a parity test** — not new math.

## Proposed endpoint

`GET /auction/bias/{symbol}` (advisory; symbol in active set MES/MGC).

Response (shape, not final):

```jsonc
{
  "symbol": "MES",
  "as_of": 1751998200.0,
  "provenance": { "is_live": false, "source": "csv_cache", "stale_after_s": 90 },
  "price": { "last": 7526.75, "prior_close": 7551.25 },
  "saty":  { "atr": 102.16, "call_trigger": 7575.86, "put_trigger": 7527.64,
             "bias": "short", "nearest_target": 7509.44,
             "day_range_pct_of_atr": 0.93 },
  "tpo":   { "value_area": 7500, "profile_target": 7624.25,
             "fail_target": 7529.75, "failed": true },
  "corey": { "bias": "bearish", "conviction": 0.6, "data_quality": "stale",
             "sellers_in_control_below": 7546.25, "buyers_offside_below": 7530.75 },
  "synthesis": {
    "line_in_sand": 7530.0,
    "long_above": 7531, "short_below": 7529,
    "confirm_long_above": 7546.25, "confirm_short_below": 7509.44,
    "lean": "flat", "overnight_recommendation": "no-edge / stand aside"
  },
  "engine_derived": true, "chart_parity": false,
  "caveats": ["range 93% of ATR — exhausted", "corey feed stale", "IB leg down — STATIC"]
}
```

- `saty.*`, `tpo.*` are computed from the engine's own modules against the live
  `prior_close` + `atr` + session OHLC — **never hardcoded**.
- `corey.*` is best-effort from ingested commentary; **nullable + quality-flagged**
  (it can be stale/absent overnight, which is when it matters most).
- `synthesis.*` is deterministic from the above (Saty bias + TPO fail-state + the
  control/offside shelves), not an LLM call.

## Widget

`dashboard/components/AuctionBiasCard.tsx`
- `"use client"` only where needed; data via **`fetchEngine('/auction/bias/MES')`**
  (never bare `fetch`), `useSWR` 60s poll.
- Renders: line-in-sand pivot, long-above / short-below, the two confirmations,
  the `lean`, and the caveats list.
- **Provenance badge** from the strict set: `live` when `is_live`, else `static`;
  a `warn` badge when `corey.data_quality == "stale"` or `day_range_pct_of_atr >= 0.9`.
- Persistent `engine-derived — not your TOS chart` label. No order controls.

## The gate: end-to-end numeric-parity test (required before render)

CLAUDE.md flags that there is **no end-to-end numeric-accuracy test** (engine → proxy
→ render). This card must not be the thing that renders a confidently-wrong number.

`engine/tests/test_auction_bias_parity.py`:
- Fixture = a known TOS screenshot's inputs (prior_close, ATR, session OHLC) with the
  on-chart values transcribed (call/put trigger, fail-target, control/offside shelves).
- Assert `/auction/bias` payload matches the transcribed values within **±1 tick**.
- Extends `test_saty_atr_levels.py::test_levels_match_live_screenshot` from the Saty
  levels to the full synthesized payload.
- CI gate: card ships only when this passes.

## Known constraints / risks (the honest "why this is hard")

1. **TOS study values have no API** — dashboard shows a re-derivation, not the chart.
   Parity depends on pinning identical inputs (tick size, RTH/ETH windows, ATR length,
   prior-close anchor); the parity test is what keeps drift visible.
2. **Cloud ↔ local data plane** — dashboard on Vercel, engine + IB Gateway on Matt's
   machine via ngrok (cf. PR #280). `is_live` is only true when the IB leg is up; ETH
   overnight it is usually asleep, so the card honestly degrades to STATIC. Card must
   show last-good value + timestamp, never imply freshness it does not have.
3. **60s-cached snapshot, not streaming** — fine for a settle-based line; a live
   level-cross alert is Phase 2 (needs a streaming path the dashboard lacks today).
4. **Advisory-only** — must never read as an auto-signal.

## Open decisions (need Matt)

- Symbols in v1: MES only, or MES + MGC?
- Overnight behavior when IB leg is down: hide the card, or show STATIC last-good?
- Corey staleness threshold before the bias is suppressed vs shown-with-warn.

## Phased plan

1. **v1** (SHIPPED, unit-tested): `analysis/auction_bias.py` synthesis +
   `routers/auction_bias_router.py` endpoint over an `AuctionDataProvider` protocol +
   `tests/test_auction_bias_parity.py` (Saty pinned to screenshot ±1 tick) +
   `tests/test_auction_bias_router.py`.
2. **v2** (SHIPPED, type-checks only): `dashboard/components/AuctionBiasCard.tsx` +
   `AuctionBias*` types in `lib/api.ts`. Not yet mounted (endpoint provider not live).
3. **v3** (SHIPPED, integration-tested with synthetic data; NOT host-verified):
   `data/auction_bias_provider.py` (`LiveAuctionDataProvider`) +
   `analysis/tpo_bias_mapping.py` (the TPO `failed`-flag derivation, unit-tested against
   the chart's own algebra) + `tests/test_auction_bias_provider.py` (6 tests, real
   `compute_tpo_profile`/`wilder_atr`/`CoreyAuctionReport` exercised against synthetic
   bars — confirms the wiring, not real-world numeric accuracy). `main.py` mount +
   host smoke test are the one remaining step — see below.
4. **v4 (later)**: streaming level-cross alerting; optional TOS bridge ingest.

## What v3 does and does not reproduce

`LiveAuctionDataProvider` (`engine/data/auction_bias_provider.py`) wires:

- **price/prior_close**: `data_manager.get_current_price(symbol, is_futures=True)`.
- **ATR**: `backtest.indicators.wilder_atr` (period 14 — its own docstring says
  "used by Saty ATR Levels script") on 30 daily bars from
  `data_manager.get_bars(symbol, lookback_days=30, timeframe="1d", is_futures=True)`.
  This is the parity-critical piece the Saty triggers depend on — confirm it reproduces
  the chart's ATR (102.16 in the 2026-07-08 fixture) in the host smoke test below.
- **TPO**: `backtest.tpo_profile.compute_tpo_profile` on 5 days of 5-min bars. The
  `failed` flag is derived by `analysis.tpo_bias_mapping.derive_tpo_failed`, grounded in
  that module's own target/fail_target algebra (verified algebraically + unit-tested
  against the 2026-07-08 fixture: bull-imbalance, target=7624.25, fail_target=7529.75,
  failed=True at 7526.75 — see `tests/test_tpo_bias_mapping.py`).
- **Corey**: `CoreyAuctionAnalystAgent.analyze()` — only `directional_bias` and
  `data_quality`/`sentiment_stale` are used. **`sellers_in_control_below` and
  `buyers_offside_below` are deliberately left `None`** — that agent's `key_levels`
  field (Discord-commentary-derived) has no confirmed mapping to those two specific
  chart shelves, which are Corey's proprietary `AA_CoreyTscorev2` ThinkScript study
  output with no API. Guessing that mapping would be exactly the
  confidently-wrong-number failure mode CLAUDE.md warns against. With them unset, the
  line-in-the-sand priority in `analysis/auction_bias.py` falls through to the TPO
  `fail_target`, then the Saty `put_trigger` — both real, engine-native numbers.

**Net honesty statement:** this card will never show Corey's exact on-chart shelf
values. It shows two independent real signals (Saty ATR triggers, engine TPO measured-move)
plus Corey's directional lean — each labeled, none faked.

## Remaining step: mount + host smoke test

**Mount (main.py, ~4 lines):**
```python
from data.auction_bias_provider import LiveAuctionDataProvider
from routers.auction_bias_router import router as auction_bias_router
from routers.auction_bias_router import inject_dependencies as inject_auction_bias_deps
# ... after data_manager is constructed:
inject_auction_bias_deps(LiveAuctionDataProvider(data_manager))
app.include_router(auction_bias_router)
```

**Smoke test**, with IB Gateway up and the live chart open side-by-side:
```bash
curl -s localhost:8010/auction/bias/MES | jq
```
Confirm, in order:
1. `saty.atr` matches the chart's ATR (was 102.16 on 2026-07-08). This is the one
   truly parity-critical check — if it's off, `saty.*` triggers will be off too.
2. `saty.call_trigger` / `put_trigger` / `plus_1_atr` / `minus_1_atr` match the chart's
   Calls/Puts/+1 ATR/-1 ATR lines (already covered by `test_auction_bias_parity.py`
   once #1 confirms the ATR feed is correct).
3. `tpo.fail_target` is in the right ballpark — exact match to Corey's chart numbers is
   **not** expected (see above); this is the engine's own measured-move, a different
   real signal, not a chart mirror.

Only after 1-2 pass: mount `AuctionBiasCard` on `/market-analysis` and confirm it
renders (not just type-checks).

---
*Design doc. v1/v2 code is unit-tested / type-checked respectively; v3 live provider is
host-only and unverified until smoke-tested. No config/risk/execution touched, no orders.*
