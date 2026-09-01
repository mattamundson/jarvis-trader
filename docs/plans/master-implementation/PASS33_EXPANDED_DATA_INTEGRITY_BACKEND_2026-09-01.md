# PASS33 - Expanded Data Integrity Backend

## Scope

- Completed backlog task `P9-001`.
- Implemented the expanded `/system/data-integrity` backend contract defined in P8-007.
- Preserved current response fields while adding explicit cache age, provider tier, bar freshness, source parity, and trade-enable blocks.

## Files

- `engine/routers/health_router.py`
  - Keeps `timestamp`, `sources`, and `count`.
  - Adds top-level `status` and `stale_after_seconds`.
  - Adds `sources[].kind`, `sources[].provider`, `sources[].provider_tier`, `sources[].age_seconds`, and `sources[].cache_key`.
  - Adds `cache_age`, `provider_tier`, `bar_freshness`, `source_parity`, and `trade_enablement`.
  - Returns explicit offline/degraded states on Redis errors or empty source sets.
- `engine/tests/test_data_integrity_stale_threshold.py`
  - Extends the existing stale-threshold tests to cover the expanded contract.
  - Adds an empty-source test proving the endpoint does not return a green state when no data sources are reported.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P9-001` done.
  - Unblocks `P9-002` and `P9-003`.

## Validation

- `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe -m pytest tests/test_data_integrity_stale_threshold.py -q` passed.
  - Result: 4 tests passed, 1 upstream Starlette/httpx deprecation warning.
- `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe -m py_compile routers/health_router.py tests/test_data_integrity_stale_threshold.py` passed.
- `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\ruff.exe check routers/health_router.py tests/test_data_integrity_stale_threshold.py --config ruff.toml` passed.
- `git diff --check` passed.

## Notes

- `provider_tier` currently reports `unknown` because provider metadata is not yet wired into the Redis freshness keys.
- `source_parity` currently reports `not_wired` by design, matching the P8-007 contract until a real parity comparison exists.
