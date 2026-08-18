# Databento Integration Plan — JARVIS TRADER (2026-08-04)

**Status:** Proposal (no purchase made; no code shipped in this doc)
**Author:** Hermes trader profile, per Amo's request for a "material, seismic boost"

---

## 1. Why Databento — the data-depth problem

The single biggest constraint discovered this session: **`INSUFFICIENT_SAMPLE` on
nearly every strategy** (17-67 OOS trades vs the 30-100 floor). Root cause is
data depth, not strategy quality:

- `data_loader.py` fetches from **Polygon.io** with `limit=50000` per call →
  ~2 years of 1h bars max (matches the 12,477-bar MES cache).
- No order-book depth anywhere — `max_volume_pct` POV impact is **estimated**,
  not measured against real liquidity.
- Regime coverage: 2024-2026 only. No 2020 crash, 2022 rate cycle, 2023 vol
  compression — the exact regimes that break trend strategies.

Databento fixes all three:
- **16+ years** of CME history (MES, MGC, MNQ, MCL, M2K + ES/GC parents).
- **MBO/MBP schemas** → real order flow → *measured* (not estimated) slippage
  and POV impact for the SOTA execution layer (PR #592/#596).
- **Point-in-time instrument definitions** (no look-ahead bias) and **smart
  rollover symbology** (continuous-contract construction without survivorship
  artifacts).

## 2. What we'd buy

| Plan | Price | What it gives |
|---|---|---|
| Usage-based historical (pay-as-you-go) | est. <$20-60 one-time for 2 symbols × 10y × OHLCV+MBO | Cheapest start; enough to validate the whole pipeline |
| **Standard subscription** | **$179/mo** | Frequently-used data, individual/small team, unlimited-ish usage |
| Enterprise/Plus | higher | Not needed at this scale |

**Recommended entry:** usage-based first ($125 free credit covers the pilot),
then Standard if live-data / high-frequency pulls become routine. The two
instruments we trade (MES, MGC) × OHLCV 1h + MBO for recent windows is small.

## 3. Dataset and schema mapping

| JARVIS need | Databento |
|---|---|
| Dataset code | `GLBX.MDP3` (CME Globex) |
| Symbol | `MES.FUT`, `MGC.FUT` (parent symbology, smart rollover) |
| OHLCV bars | schema `ohlcv-1h` (or build from `trades`/`mbp-1` with `db.BarType`) |
| Order book (for impact) | schema `mbp-1` (10-level) or `mbo` (full depth) |
| Point-in-time metadata | schema `definition` (no retroactive adjustments) |

## 4. Integration design (additive, zero disruption)

New module `engine/backtest/databento_loader.py`, **parallel** to the existing
Polygon loader. Same output contract: a `pd.DataFrame` with
`timestamp/open/high/low/close/volume` (plus optional `bid/ask/depth` columns
for the SOTA layer). The runners already call `_find_latest_cache()` /
`_resolve_data()` — swap the source behind that seam.

```python
# engine/backtest/databento_loader.py (proposed)
import databento as db

client = db.Historical("YOUR_API_KEY")

# 10-year OHLCV-1h for MES with smart rollover (no look-ahead)
data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="ohlcv-1h",
    symbols="MES.FUT",
    stype_in="parent",
    start="2015-01-01",
    end="2026-08-04",
)
df = data.to_df()  # normalized schema
```

Key integration points:
1. **Loader seam** — `_resolve_data()` in runners gains a
   `source: "polygon" | "databento"` param (default `polygon`, backward
   compatible).
2. **Cache format** — keep writing CSV (or move to ArcticDB, see below); the
   existing `MES_2024-04-26_2026-06-25_1h.csv` remains valid.
3. **Bar quality gate** — `screen_bars()` runs identically on Databento frames
   (it's schema-agnostic OHLCV).
4. **SOTA execution** — when MBO/MBP columns are present, upgrade
   `_apply_execution_costs()` from `max_volume_pct` estimate to measured
   depth-at-touch (institutional-grade impact).
5. **Live/paper** — no change. This is purely a research-data upgrade.

## 5. Migration steps (when approved)

1. `pip install databento` into the engine venv; set `DATABENTO_API_KEY` in
   `engine/.env` (never commit).
2. Pilot pull: MES + MGC, `ohlcv-1h`, 2015→2026 (usage-based, ~$free with
   credit). Validate bar count vs current 12,477 (expect ~10×).
3. Write `databento_loader.py` behind the loader seam; run 2-3 existing
   runners (rank4 MGC, rv_filter) on the deep data → measure OOS trade count
   growth and verdict stability.
4. If OOS sample jumps 17→150+ and verdicts stabilize → this is the seismic
   fix: the sample-adequacy gate stops being the binding constraint.
5. Optional second phase: pull `mbp-1` for recent 6-12 months, wire measured
   impact into `_apply_execution_costs`.

## 6. Risk / safety notes

- **No live-trading change.** Research data only.
- API key hygiene: `DATABENTO_API_KEY` goes in `engine/.env` (gitignored),
  never in committed files. Credential guard already blocks known paths.
- Cost control: usage-based is capped by request size; the pilot is tiny.
- [ASSUMPTION] Pricing/feature facts from databento.com (2026-08-04 search):
  Standard $179/mo, usage-based historical available, $125 new-user credit,
  16+ years CME history, GLBX.MDP3 dataset code. Verify current terms on the
  account page before purchase.

## 7. Decision request

- **Approve pilot pull** (usage-based, ~free with credit): I create the
  Databento account flow + loader + validation run.
- **Approve Standard $179/mo**: only after pilot proves the OOS-sample gain.
- Alternative: stay on Polygon, extend pull windows (but Polygon `limit=50000`
  is a hard cap; depth data unavailable).

---

## 8. Polars/ArcticDB benchmark — NOT worth it at current data size (2026-08-04)

Tested the "free speed" recommendation against reality before committing to it.
Built `engine/backtest/cache_loader_polars.py` (drop-in Polars cache loader,
same pandas contract) and benchmarked on the real widest MGC cache
(MGC_2024-04-26_2026-06-25_1h.csv, ~12.5k rows):

    pandas 0.027s | polars 0.056s | speedup 0.5x

**Polars is 2x SLOWER on this workload.** Root cause: the cache files are tiny
(12k rows), and converting Polars back to the pandas contract (which the whole
engine expects) eats the I/O gain. Polars only wins at 10x+ the data size or
when staying in Polars end-to-end (a rewrite of every runner for zero measured
benefit today).

**Sequencing correction:** the Polars/ArcticDB speed-up is only worth doing
AFTER Databento deepens the data (10x more bars). At current sizes it's a
solution looking for a problem. The loader module is kept in the tree as the
ready seam for when deep data arrives, but it is NOT recommended for
activation at current data volumes. [ASSUMPTION] benchmarks are on this host;
larger Databento pulls may flip the result — re-benchmark after the pilot.
