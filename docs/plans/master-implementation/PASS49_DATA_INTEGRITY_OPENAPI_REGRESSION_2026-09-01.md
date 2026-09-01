# PASS49 - Data Integrity OpenAPI Regression

## Scope

- Completed `P10-006`.
- Added an OpenAPI regression to `engine/tests/test_data_integrity_stale_threshold.py`.
- The test pins `/system/data-integrity` 200 responses to `DataIntegrityResponse` and verifies the expanded contract properties remain present.

## Evidence

- The regression asserts schema coverage for:
  - `sources`
  - `cache_age`
  - `provider_tier`
  - `bar_freshness`
  - `source_parity`
  - `trade_enablement`
  - optional `error`

## Validation

- `python -m pytest tests/test_data_integrity_stale_threshold.py -q` passed: 5 tests.
- `python -m py_compile api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py` passed.
- `ruff check api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py --config ruff.toml` passed.

## Next Action

- Continue with `P10-007`: wire provider metadata into the data-integrity provider-tier status.
