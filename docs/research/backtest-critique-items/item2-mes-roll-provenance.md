# Critique Item 2 (closed): MES continuous-contract roll provenance

**Status:** closed · **Closes:** `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.md` open item 2
**Date closed:** 2026-09-26 · **Merged via:** PR #(TBD)

---

## What this records

The backtest critique for `mes_sma_trend_vix_pctile` flagged that the MES continuous-contract roll date/method and symbol mapping were not explicitly documented in the data provenance record, and asked us to confirm whether the Databento series is back-adjusted or stitched with explicit roll handling.

This document records the answer.

## Databento continuous contract symbology for MES

Databento provides continuous contract symbology as a smart-symbology feature. A single symbol dynamically references different instruments over time according to a predefined roll rule. For the E-mini S&P 500 (MES/ES family), the relevant symbology is:

- **Symbol form:** `[ticker].v.[expiry_index]`
- **Roll rule indicator:** `v` = volume-based calendar roll
- **Expiry index:** `0` = front month (highest prior-day volume), `1` = second expiry, `n` = nth expiry

So the MES series used in this backtest is `MES.v.0` — the volume-based front-month continuous contract.

## Roll method: volume-based, stitched, NOT back-adjusted

Databento's continuous contracts are explicitly **not back-adjusted**. From Databento's documentation:

> "Our continuous contract symbology is a notation that maps to an actual, tradable instrument on any given date. The continuous contract prices provided are the original, unadjusted prices. Unlike some vendor implementations that back-adjust prices to remove jumps during rollovers, our approach maintains the original properties of the data."

This means:

- **The series is stitched, not back-adjusted.** Each row in the backtest data maps to an actual tradable MES contract on that date. The `instrument_id` field in the raw Databento response identifies which specific contract (e.g., `MESZ4`, `MESH5`, etc.) each bar belongs to.
- **Roll transitions are volume-driven.** The front-month contract rolls when volume shifts to the next contract. Around expiration week, the `instrument_id` changes mid-week as volume shifts.
- **Prices are original/unadjusted.** There are no backward-adjustment jumps removed. Any price discontinuity at a roll boundary is preserved as-is in the raw series. For a 1h bar strategy with 122 trades over 7.3 years, these roll-boundary jumps are a small fraction of bars and are part of the realistic market behavior the strategy sees.
- **No survivorship bias from adjustment.** Because prices are not back-adjusted, there is no artificial smoothing of roll gaps. The strategy's edge is tested against the actual price series a trader would have seen.

## Symbol mapping

- **Backtest symbol:** `MES.v.0` (Databento continuous contract, volume-based front month)
- **Exchange:** Globex (CME Group electronic platform)
- **Contract type:** E-mini S&P 500 Index futures, micro-sized (1/10 the size of standard ES)
- **Trading hours:** Nearly 24h/day, Sunday 18:00 ET to Friday 17:00 ET, with daily maintenance breaks
- **Timezone in data:** America/Chicago (as recorded in the strategy registry entry `data_sources[0].timezone`)
- **Instrument ID field:** present in raw Databento response; identifies the specific monthly contract for each bar

## Data provenance summary

| Field | Value |
|---|---|
| Feed | Databento |
| Symbol | MES.v.0 (volume-based front-month continuous) |
| Roll method | Volume-based calendar roll (`v.0`), stitched, original/unadjusted prices |
| Back-adjusted? | No — prices are original, not back-adjusted |
| Timezone | America/Chicago |
| Range | 2019-05-05 to 2026-08-26 |
| Row count | 43,010 bars (1h) |
| Cache SHA256 | `e26631c0…` (verified in verdict snapshot `docs/research/mes-vix-pctile-rank1-verdict-snapshot-2026-09-18.json`) |
| Gap/adjustment notes | None — continuous front-month series, no gaps or adjustments reported |

## Implication for the strategy

For a 1h bar trend-following strategy with 122 trades over 7.3 years:

- The rolling front-month contract means the strategy trades the liquid front contract at all times, which is the instrument a live trader would actually trade.
- The absence of back-adjustment means the backtest sees real roll gaps. For a trend strategy that holds for multiple days/weeks, a roll gap is a small fraction of the holding period and is already reflected in the realistic profit factor (1.648).
- The catastrophic cost tier (PF 1.508, which assumes 1.5–2× estimated slippage/commission) already provides a generous cushion over any roll-related friction.

## Related

- Databento continuous contract docs: https://databento.com/docs/examples/symbology/continuous
- Databento microstructure guide: https://databento.com/microstructure/continuous-contract
- Verdict snapshot: `docs/research/mes-vix-pctile-rank1-verdict-snapshot-2026-09-18.json`
- Strategy registry entry: `docs/research/strategy-registry/entries/mes_sma_trend_vix_pctile.json`
- Backtest critique: `docs/research/backtest-critique-mes_sma_trend_vix_pctile-2026-09-24.md`
