# FRED / macro data adapter spec (Wave 5 — repo-mining consolidation)

**Date:** 2026-09-12
**Mined from:** `mattamundson/fredapi` (vendored copy at
`C:/Users/mattm/AppData/Local/Temp/consolidation_mining2/fredapi`, fredapi 0.5.1)
**Related:** `docs/research/macro-regime-context-spec.md` (contract),
`docs/setup-guides/FRED_API.md` (key setup), `docs/research/reference-repo-mining/2026-09-12-wave2-reference-mining.md` §5
**Scope:** docs/spec only. No engine code changed. No live config, risk, or routing touched.

This spec turns the "FRED/macro data adapter" backlog item into a concrete
adapter contract between the `fredapi` library and the three engine touchpoints
that consume macro data today:

| Engine touchpoint | File | Role |
|---|---|---|
| Snapshot service | `engine/data/fred_data.py` | `FREDDataService.get_macro_snapshot()`, yfinance fallback `get_live_macro_yfinance()` |
| HTTP surface | `engine/routers/macro_router.py` | `GET /macro/snapshot` (5-min cache, VIX enrichment via data_manager) |
| Backtest regime | `engine/backtest/macro_regime.py` | stale>5d → `UNKNOWN` fail-safe regime labeling |
| Event gate | `engine/data/macro_calendar.py` | hardcoded 2026 NFP/CPI/FOMC windows, -30/+60 min block |

## 1. What fredapi actually gives us (mined capability map)

`fredapi.Fred` wraps the FRED/ALFRED REST endpoints. The methods that matter
for JARVIS, in priority order:

| fredapi method | What it returns | JARVIS use |
|---|---|---|
| `get_series(id, start, end)` | latest-known values, observation-date indexed | current snapshot path (already used) |
| `get_series_as_of_date(id, as_of_date)` | values **including only revisions whose `realtime_start <= as_of_date`** | **point-in-time backtests — the headline gap** |
| `get_series_first_release(id)` | original prints only, revisions ignored | pessimistic PIT variant |
| `get_series_all_releases(id)` | DataFrame `(date, realtime_start, value)` — every vintage row | revision audit / feature-stability studies |
| `get_series_vintage_dates(id)` | list of revision dates | data-quality monitors |
| `get_series_info(id)` | units, frequency, release source, last-updated | registry metadata for each series |

Key ALFRED semantics (from the library docs): every observation carries three
dates — `date` (period it describes), `realtime_start` (first date the value
was known), `realtime_end` (last date it was valid before supersession).
Example: 2014Q1 GDP printed 17149.6 on 2014-04-30, revised to 17101.3 on
2014-05-29. A backtest run as of 2014-05-01 must see 17149.6, never the
revision.

## 2. Gap analysis vs. the macro-regime contract

`docs/research/macro-regime-context-spec.md` demands per-series: vintage
policy, release/effective timestamps, freshness threshold, revision handling,
missing-data behavior. Current engine state:

1. **PIT in backtests: not implemented.** `FREDDataService` only calls
   `get_series` (latest-known). Any macro feature joined into a historical
   backtest today is survivorship-of-revisions contaminated. `fredapi` already
   solves this with `get_series_as_of_date`; the adapter must expose it as the
   **only** backtest-facing call path.
2. **Silent-default hazard.** `get_latest()` falls back to
   `FRED_SNAPSHOT_DEFAULTS` (hardcoded Q1 2026 values) with only a log
   warning. A stale default can masquerade as live data on the dashboard and
   in agent context (fundamental_analyst / risk_manager / pipeline all poll
   `/macro/snapshot`).
3. **Doc/behavior mismatch.** `docs/setup-guides/FRED_API.md` says the
   endpoint 422s without a key; `fred_data.py` instead degrades to defaults,
   and a yfinance path bypasses FRED entirely. [ASSUMPTION: guide text is
   pre-degradation-era; not re-verified against a live engine this wave.]
4. **Release-calendar drift.** `macro_calendar.py` hardcodes 2026 catalyst
   dates through ~Sep; beyond that the entry-block gate silently has no
   windows. FRED's release API (or `get_series_info` last_updated) could
   drive this, but any change to entry-gating behavior is [safety-review]
   territory — out of scope for this spec's implementation phase.

## 3. Adapter contract (target state)

A thin `MacroAdapter` layer over `FREDDataService` with two strictly separated
modes. Rule: **live mode never answers backtest questions; PIT mode never
serves the dashboard.**

### 3.1 Live/snapshot mode (context only — today's path, hardened)

```
get_snapshot(as_of=now) -> {
  values: {series_id: {value, units, freq, observation_date, realtime_start}},
  stale: [series_id],          # value older than per-series freshness threshold
  defaulted: [series_id],      # FRED_SNAPSHOT_DEFAULTS substituted — EXPLICIT, not silent
  source: "fred" | "yfinance" | "defaults",
}
```

Requirements:
- Per-series freshness thresholds (VIXCLS daily: 5 business days; monthly
  series: 45 days) surfaced in the payload, mirroring
  `macro_regime.py`'s existing `stale_days` fail-safe.
- `defaulted` must be plumbed through `/macro/snapshot` so dashboard and
  agents can show/penalize fallback values. No response may present a
  hardcoded default as a live print without the flag. [RISK: changing the
  response shape touches dashboard consumers — do it additively, new keys
  only.]
- `source` provenance per value; yfinance-sourced values must never be
  labeled FRED.

### 3.2 Point-in-time mode (backtest/feature engineering)

```
get_pit_series(series_id, as_of_date, observation_start) -> Series
  # MUST be backed by fredapi get_series_as_of_date (realtime_start <= as_of_date)
```

Requirements:
- Visible-at-time only: a value may not appear in a backtest feature frame
  before its `realtime_start`. This is the acceptance test the
  macro-regime spec already calls for: a tiny fixture proving a revision to
  2014Q1 GDP dated 2014-05-29 is absent from the 2014-05-01 view and the
  first print is present.
- Cache full vintages locally (`get_series_all_releases` → parquet/jsonl
  under `engine/data/` cache dir) and slice by `realtime_start` in-process;
  don't re-hit the API per backtest bar.
- ALFRED rate limits (120 req/min) ⇒ bulk snapshot at EOD, not per-run
  fetches.

### 3.3 Series registry

Each series used by JARVIS gets a registry row (extend the strategy-registry
pattern):

```
series_id | display | freq | units | freshness_days | pit_required | consumers
VIXCLS    | VIX     | daily| index | 5              | yes          | regime, snapshot, brief
FEDFUNDS  | FFR     | monthly| %   | 45             | no (rarely revised) | snapshot
GS10/GS2  | yields  | daily| %     | 5              | no           | curve, snapshot
CPIAUCSL  | CPI     | monthly| idx | 45             | YES (revisions) | inflation features
PCEPI     | PCE     | monthly| idx | 45             | YES          | inflation features
GDP/A191RL1Q225SBEA | growth | quarterly | % | 120 | YES       | regime
```

(`pit_required: YES` = fredapi shows material revision history AND the series
enters a backtest feature; latest-only is acceptable for display-only series.)

## 4. Non-goals / guardrails

- Macro features remain **context and regime labels only** — they must not
  bypass gate_v2 promotion or alter live sizing (macro-regime spec §Safe
  usage; unchanged here).
- No changes to `macro_calendar.py` entry-block windows in the implementation
  PR — calendar refresh is an **order-behavior gate** and requires a
  [safety-review] PR on its own.
- No new required dependency: `fredapi==0.5.2` is already pinned in
  `engine/requirements-core.txt` (mining copy reviewed here is 0.5.1; the
  ALFRED methods cited exist in both); the adapter uses it optionally and
  degrades exactly as `FREDDataService` does today.
- Vendor code stays vendored-at-reference only; we import the library, we do
  not fork it into the engine.

## 5. Implementation slices (each independently mergeable)

1. **S-1 PIT reader** — `FREDDataService.get_series_as_of_date` passthrough +
   vintage cache + the release-lag fixture test. Tests-only evidence, no
   consumer changes.
2. **S-2 Snapshot honesty fields** — add `stale`/`defaulted`/`source` keys to
   `/macro/snapshot` (additive), badge on dashboard macro panel later.
3. **S-3 Series registry file** — YAML/json registry per §3.3 consumed by
   S-1/S-2 thresholds.
4. **S-4 Calendar refresh plan** — evaluation doc proposing
   [safety-review] automation for `macro_calendar.py` catalyst windows.

## 6. Verification performed for this doc

- Read `fredapi/fred.py` (0.5.1) method surface directly from the vendored
  mining copy: `get_series_as_of_date`, `get_series_first_release`,
  `get_series_all_releases`, `get_series_vintage_dates` confirmed present
  with the semantics quoted above.
- Cross-checked every engine claim against `origin/master` @ `d9ea4fe9`:
  `engine/data/fred_data.py` (defaults table, fallback logging),
  `engine/routers/macro_router.py` (300 s cache, VIX enrichment),
  `engine/backtest/macro_regime.py` (5-day stale → UNKNOWN),
  `engine/data/macro_calendar.py` (hardcoded 2026 windows, -30/+60 block).
- Confirmed consumers of `/macro/snapshot` via `git grep`:
  `agents/fundamental_analyst.py`, `agents/pipeline.py`,
  `agents/risk_manager.py`, `api_check.py`.
