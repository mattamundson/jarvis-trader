# FRED / ALFRED transport resilience checklist (Wave 19)

**Date:** 2026-09-13
**Mined from:** `mattamundson/fredapi` default branch `master`, tree `d0a0ba3001ebbbceafdcbdd3eb23828f0537cdff`
**Extends:** `docs/research/fred-macro-data-adapter-spec.md` (Wave 5)
**Scope:** docs/checklist only. No engine code, live trading config, risk limits,
kill-switch, broker routing, `.env`, PM2, active instrument gates, or order behavior changed.

Wave 5 defined the **macro adapter contract**: live snapshot mode, point-in-time
backtest mode, series registry, and [safety-review] boundaries around event-gate
automation. This Wave 19 deeper pass focuses on the lower-level transport and
resilience lessons visible in `fredapi` itself: request construction, proxy
handling, XML parsing, pagination, error semantics, and offline test fixtures.

## 1. Fresh source readback summary

Files read from `mattamundson/fredapi`:

| File | Evidence mined | JARVIS implication |
|---|---|---|
| `fredapi/fred.py` | `Fred.__init__`, `__fetch_data`, ALFRED release methods, search pagination | Adapter must isolate network side effects and avoid per-bar remote fetches. |
| `fredapi/tests/test_fred.py` | mocked XML fixtures, fake API key, invalid ID/error-path tests | JARVIS tests can cover FRED logic offline with tiny XML fixtures. |
| `fredapi/tests/test_with_proxies.py` | proxy constructor smoke path using `proxies={http,https}` | Proxy support needs a process-local wrapper; the raw library mutates global opener state. |
| `README.md` | ALFRED vintage examples and public usage semantics | Backtest-facing macro features must state vintage policy and revision visibility. |

Fresh readback found **new leverage beyond Wave 5**: Wave 5 covered *what* the
macro adapter should expose; it did not specify the transport-failure boundaries
that keep FRED from silently contaminating a long-running trading engine.

## 2. Hazards mined from `fredapi`

### H-1: client construction is not guaranteed side-effect free

`Fred.__init__(api_key=None, api_key_file=None, proxies=None)` accepts explicit
proxy dictionaries and also reads `HTTP_PROXY` / `HTTPS_PROXY` from the process
environment. If proxies exist, it creates a `ProxyHandler` and calls
`urllib.request.install_opener(opener)`.

JARVIS rule:
- Do **not** construct raw `Fred(...)` in many modules. Centralize it behind one
  macro transport factory.
- The transport factory must record whether proxy settings came from explicit
  configuration, inherited environment variables, or were absent.
- [RISK] Do not edit `.env` or machine proxy settings from this adapter work;
  proxy changes are environment operations, not trading research changes.
- A future implementation should prefer process-local request handling where
  possible. If `fredapi`'s global opener must be used, instantiate it once at
  startup and treat proxy state as immutable for the process lifetime.

Acceptance tests:
- With no proxy env vars, client creation reports `proxy_source=none`.
- With explicit proxy settings in a unit fixture, client creation reports
  `proxy_source=explicit` and does not leak credentials into logs.
- With inherited proxy env vars, telemetry reports `proxy_source=environment` so
  future feed failures can be diagnosed without exposing proxy values.

### H-2: `fredapi` does not set an explicit timeout

`fredapi.__fetch_data(url)` calls `urlopen(url)` and parses the response XML. No
request timeout is passed in the mined source.

JARVIS rule:
- Any JARVIS wrapper around FRED must enforce an adapter-level timeout. A macro
  feed call may degrade the snapshot; it may not hang the engine, morning brief,
  dashboard, or research worker indefinitely.
- Timeout should be short for live snapshot context and longer only for bulk
  offline vintage-cache refreshes.

Recommended defaults for a future implementation:

| Mode | Timeout | Retry budget | Degradation behavior |
|---|---:|---:|---|
| Live snapshot | 3s connect/read envelope | 0-1 retry | Return stale/default flags; do not block pipeline. |
| Morning brief / dashboard refresh | 5s | 1 retry | Mark macro panel degraded; preserve last known good timestamp. |
| Bulk ALFRED cache refresh | 20s per request | bounded exponential backoff | Fail the refresh artifact; never partially certify PIT cache. |

Acceptance tests:
- A fake transport that sleeps past timeout yields a degraded snapshot with
  `source=timeout` or equivalent provenance.
- Timeout degradation does not change live order/risk/sizing decisions.
- Bulk refresh timeout leaves the previous certified vintage cache intact.

### H-3: XML error bodies are meaningful and should be surfaced safely

`fredapi.__fetch_data` catches `HTTPError`, parses the XML body, and raises
`ValueError(root.get('message'))`. `fredapi/tests/test_fred.py` includes invalid
series-ID coverage around this behavior.

JARVIS rule:
- Adapter errors should keep the upstream message for operator diagnosis, but
  redact request parameters that could include secrets.
- Store structured error categories (`auth`, `rate_limit`, `invalid_series`,
  `timeout`, `parse_error`, `network`) rather than only raw exception strings.
- A missing/invalid FRED key and an invalid series ID are different failures:
  key/auth affects all macro series; invalid ID is a registry defect.

Acceptance tests:
- Invalid series fixture maps to `invalid_series` with the series ID and no API
  key in logs.
- HTTP 429 fixture maps to `rate_limit` and trips refresh backoff, not a silent
  default-as-live state.
- Malformed XML maps to `parse_error` and marks the affected series unusable.

### H-4: latest-value snapshots and ALFRED vintage slices must use separate caches

Wave 5 already requires separate live and point-in-time modes. The deeper source
readback reinforces why: `get_series(...)` returns latest-known values while
`get_series_all_releases(...)` returns duplicate observation dates with separate
`realtime_start` values.

JARVIS rule:
- Never store latest-only snapshot rows in the same artifact namespace as ALFRED
  all-release/vintage rows.
- PIT caches need at least `(series_id, observation_date, realtime_start, value,
  source, fetched_at, adapter_version)`.
- Latest snapshot caches need at least `(series_id, latest_observation_date,
  value, source, fetched_at, stale_after)`.

Acceptance tests:
- A latest-only snapshot fixture cannot satisfy a PIT cache loader.
- A PIT fixture with two revisions for one observation returns only the revision
  visible as of the requested `as_of_date`.
- Cache provenance survives CSV/parquet/jsonl round trips.

### H-5: search/category/release discovery can require pagination

`fredapi.__get_search_results(...)` uses `count`, `limit`, and `offset` because
FRED search endpoints cap result pages. It treats `limit=0` as all available
results.

JARVIS rule:
- Series discovery is an offline research operation, not a live request path.
- Discovery jobs must persist `(query/release/category, count, returned,
  offsets_seen)` in evidence so a truncated page cannot masquerade as a complete
  candidate universe.
- Do not let a broad FRED search run inside strategy execution or dashboard route
  handlers.

Acceptance tests:
- Two-page fixture (`count > 1000`) verifies offset handling and final row count.
- Partial page failure marks the discovery artifact incomplete.
- Live snapshot code path has no dependency on search/category/release discovery.

## 3. Implementation slices

Each slice is independently mergeable and keeps macro data as context/research,
not execution authority.

### S-1: Macro transport factory and telemetry

Add a narrow wrapper around `fredapi.Fred` construction:

```text
make_fred_client(api_key: str | None, proxies: dict | None, timeout_profile: str)
  -> FredClientHandle(client, proxy_source, timeout_profile, created_at)
```

Acceptance criteria:
- Unit tests use monkeypatched environment variables and a fake Fred class.
- Logs expose proxy source and timeout profile, not proxy values or API keys.
- No caller instantiates `Fred(...)` directly outside the wrapper after the slice.

### S-2: Error taxonomy for macro fetches

Normalize exceptions from FRED/yfinance/default paths into structured categories.

Acceptance criteria:
- Auth/rate-limit/invalid-series/timeout/parse-error/network fixtures each map to
  a deterministic category.
- `/macro/snapshot` remains backward compatible; new provenance fields are
  additive only.
- No engine/risk/kill-switch/order files changed unless a dedicated
  [safety-review] PR is opened.

### S-3: Certified offline fixtures for ALFRED semantics

Commit tiny XML fixtures copied from the mined `fredapi` tests/README pattern,
not large downloaded datasets.

Acceptance criteria:
- Test proves first print vs revised GDP behavior without internet or API key.
- Test proves malformed XML and invalid ID behavior.
- Test proves missing values `.` are represented as NaN and never converted to
  zero.

### S-4: Bulk vintage refresh evidence contract

Document and later implement a refresh artifact that can be checked before a
backtest consumes macro features.

Minimum artifact fields:

```text
series_id
requested_realtime_start
requested_realtime_end
row_count
observation_min_date
observation_max_date
vintage_min_realtime_start
vintage_max_realtime_start
source_tree_or_package_version
fetched_at
complete: true|false
error_category: null|string
sha256
```

Acceptance criteria:
- Backtests only consume `complete=true` certified artifacts.
- A failed refresh never overwrites the last certified artifact.
- Revision rows are audited by observation date and realtime start before any
  macro feature is joined to historical bars.

## 4. Non-goals / safety boundaries

- No automated update to `engine/data/macro_calendar.py` in this wave. Calendar
  entry-block windows can affect order behavior and require [safety-review].
- No new FRED key provisioning, `.env` edit, proxy edit, PM2 action, or live
  engine restart.
- No dependency bump. This checklist was mined from a 0.5.1 source tree while
  JARVIS previously documented `fredapi==0.5.2` in the implementation target;
  transport wrappers should verify the installed version when implemented.
- No vendor-code import. Use `fredapi` as a dependency/reference, not a copied
  source subtree.

## 5. Verification performed for this checklist

- GitHub auth and remote repo readback confirmed:
  `mattamundson/fredapi`, default branch `master`, pushed `2026-04-22T22:48:52Z`.
- Recursive GitHub tree readback returned `14` blobs, `truncated=false`, tree
  `d0a0ba3001ebbbceafdcbdd3eb23828f0537cdff`.
- Selected-source manifest written locally with `11` text files from fredapi at
  `C:/Users/mattm/AppData/Local/Temp/repo_consolidation_sources/wave19_source/selected_files_manifest.json`.
- Wave 5 master doc read back from GitHub and compared for scope:
  `docs/research/fred-macro-data-adapter-spec.md`, SHA256
  `c7ba249400bdb88fa49330950e81a641c86e1a203f1e1b806db211207406baa4`.
- Current JARVIS master macro files read back for context:
  `engine/data/fred_data.py`, `engine/routers/macro_router.py`,
  `engine/backtest/macro_regime.py`, `docs/setup-guides/FRED_API.md`.
