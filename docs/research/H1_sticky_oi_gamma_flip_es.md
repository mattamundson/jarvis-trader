# H1 — Sticky-OI gamma flip vs 30-minute ES return

**Registered:** 2026-10-26
**Status:** PRE-REGISTERED. No sample has been scored. No subscription is authorized by this note.
**strategy_id:** `h1_sticky_oi_gamma_flip_es`
**promotion_state:** `research_only`

This is the first falsifiable hypothesis from the 2026-10-26 market-edge reconstruction. It replaces the vendor shopping list. A later agent scores this record. It does not add features, horizons, or symbols after seeing results.

## Hypothesis

On non-event regular-hours sessions, the sign of ES minus a gamma-flip level computed once from the prior session's options chain has no positive 30-minute expectancy at 09:35 America/Chicago after a fixed cost.

**H0 (what a pass must beat):** the cost-adjusted mean 30-minute point change, signed by the position rule below, is less than or equal to zero.

**H1 (the claim under test):** that mean is greater than zero on the estimation sample, the day-clustered 95% bootstrap interval lies entirely above zero, and the held-out block keeps the same sign.

## Position rule

Frozen before any look at outcomes.

- Decision time: 09:35 America/Chicago. The 09:30 open bar is context only.
- Let `flip` be the zero-gamma strike from `compute_gex` in `engine/analytics/options_flow.py`, fit on the prior completed session's chain and that session's close as `spot`. Hold `flip` fixed for the whole next session. Do not reprice it with the intraday spot. Intraday `GEX(S,t)` is a different hypothesis and is not registered here.
- Let `es` be the ES (or MES, same index points) trade price at 09:35.
- If `es < flip`, the signed position is short. If `es > flip`, the signed position is long. If `es == flip`, the session is a skip, not a flat-that-counts-as-a-win.
- Outcome: ES point change from 09:35 to 10:05, signed by the position, minus 0.50 index points. That 0.50 is one ES tick (0.25) of cost on entry and one on exit. MES dollar conversion, if reported, uses $5 per index point and is not a second test.
- One observation per session. Overlapping 5-minute labels are out of this record.

## Chain contract

- Underlying for the chain: SPX if a point-in-time SPX chain with gamma and open interest exists. Otherwise SPY, with the flip multiplied by 10 before it is compared with ES, and that scale factor written on every row.
- Dealer sign is the one already in `compute_gex`: calls `+1`, puts `-1`. Dollar GEX uses `sign * gamma * open_interest * multiplier * spot^2 * 0.01`. A constant multiplier does not move the zero crossing. SPX and SPY use multiplier 100. Do not silently switch to an ES-options multiplier.
- Gamma and open interest are as of the prior session close. A chain timestamp after 09:35 on the decision day is lookahead and voids the row.
- The flip is a model on assumed dealer signs. It is not a measurement of the dealer book. Rows store `flip`, `net_gex`, and `chain_asof`. They do not store a claim about dealer inventory.

## Sample

- Instrument: ES price, MES as the only instrument that could later be paper-shadowed. MNQ, NQ, MCL, M2K, and MGC are outside this record. MNQ is halted in the engine.
- Session filter, all of these must hold or the day is excluded and listed in the exclusion log:
  - FOMC decision day
  - CPI day
  - Employment-situation (NFP) day
  - SPX monthly expiration (third Friday) and the Thursday before it
  - Last business day of the month
  - Last business day of March, June, September, December is already inside month-end; tag it `quarter_end` as well so the exclusion is visible
- Estimation sample and held-out sample are split by time, not by random row. The last 60 eligible sessions are held out and are not used to choose a threshold, a strike filter, or a horizon.
- Minimum estimation sample: 250 eligible sessions. Below that the only legal status is `INSUFFICIENT`.

## Kill rules

Apply in order. The first hit is the verdict.

1. Chain timestamps or the 09:35 price cannot be shown to be known at decision time: `INVALID`, do not interpret the mean.
2. Eligible estimation sessions `< 250`: `INSUFFICIENT`. Do not buy data to "get a result" inside this same record. A data-gap note is allowed. A new record is required before a wider pull is scored.
3. Day-clustered bootstrap, 95% interval, of the cost-adjusted signed point change includes zero: `RETIRE`.
4. The held-out 60-session mean has the opposite sign from the estimation mean: `RETIRE`.
5. The estimation mean is positive only when the excluded event days are put back in: `RETIRE` as an event-flow confounder. Record the event-day mean in an appendix. It is not a pass.
6. Any pass that depends on vanna, charm, a second vendor's GEX, a same-day visual match, or a model trained on these labels: `INVALID`.

A `PASS` here means H0 was rejected under the rules above. It does not authorize an order, a paper config change, or a gate-v2 bypass. The next state, if ever requested, is a separate paper-shadow record on MES with the engine kill switch untouched.

## What this record does not test

- Flip velocity, flip acceleration, time spent above the flip.
- Intraday reprice `GEX(S,t)` or `GEX(S,t,sigma)`.
- CVD, footprint, DOM, absorption, MBO.
- Dark-pool prints, Unusual Whales flow, Azrael king-node or expected-move shelves.
- Any horizon other than 30 minutes from 09:35.
- NQ or MNQ.

Those stay unregistered until this record is `RETIRE` or `INSUFFICIENT` for a reason that names which missing measurement would change the verdict.

## Data and money

Existing pieces, in this order:

1. `engine/analytics/options_flow.py` `compute_gex` — pure function, already unit-tested on a hand-computed one-contract case (`net_gex = 5_000_000` at spot 100, gamma 0.05, OI 1000, call).
2. MES price history already used by the engine. This hypothesis needs the 09:35 and 10:05 prints, not a new Sierra feed.
3. A prior-close chain with gamma and open interest. If that history is absent, the legal next purchase is one historical options pull under `docs/plans/JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md` (Databento OPRA on the existing credit, or data already entitled). That plan's $0 pilot still stands.

Not authorized by this record:

- ThetaData Options Standard at $80. Options Value at $40 is the intraday candidate in the 2026-09-23 budget note, and only after this record is `INSUFFICIENT` because the chain is too coarse to timestamp. It is not the first invoice.
- Sierra Chart, Denali, CME depth. The $13.50 non-professional depth fee requires Sierra connected to a live funded futures account. The engine's live Gateway port 4001 is read-only market data. Connecting a second session to it is a duplicate-IB risk and is not part of H1.
- Unusual Whales API.
- A new live funded account.
- Edits to `engine/config.py`, `engine/risk/`, or the kill switch.

## Row the scorer must be able to rebuild

`session_date`, `chain_asof`, `chain_underlying`, `spot_used`, `flip`, `net_gex`, `es_0935`, `es_1005`, `es_spx_basis_0935`, `signed_points`, `cost_points` (always 0.50), `net_points`, `exclusion_tags`.

Immutable once a scoring run starts. A changed formula is a new record, not an edit of the scored rows.

## Known failure modes

- Dealer-sign convention can be wrong in aggregate. The test then measures a labeled model, which is what was registered. It still does not measure dealer inventory.
- Prior-close gamma is not the gamma at 09:35. That bias is accepted in H1. It is the reason a dynamic reprice is a later record, not a silent fix.
- ES–SPX basis moves the distance. `es_spx_basis_0935` is stored. It is not a fitted hedge in the primary mean.
- Third-Friday and macro calendars can be mis-tagged. The exclusion log is part of the evidence. An unlogged event day inside the estimation sample makes the run `INVALID`.

## Evidence paths

- Calculator: `engine/analytics/options_flow.py`
- Known-input tests: `engine/tests/test_options_flow.py`
- Prior canonical writeup, not a pass: `docs/research/bookmark-edge-scan-2026-07-02.md` (dealer-gamma regime, data-gated)
- Budget sequence this record obeys: `docs/plans/JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md`
- Source reconstruction, not evidence of an edge: the 2026-10-26 combined market-edge history
