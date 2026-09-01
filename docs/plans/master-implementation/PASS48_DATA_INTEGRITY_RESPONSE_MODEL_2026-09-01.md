# PASS48 - Data Integrity Response Model

## Scope

- Completed `P10-005`.
- Added explicit Pydantic response models for the expanded `/system/data-integrity` contract in `engine/api/models.py`.
- Bound `engine/routers/health_router.py` to `response_model=DataIntegrityResponse`.
- Unblocked `P10-006` and `P10-007`.

## Evidence

- The response model covers:
  - `sources`
  - `cache_age`
  - `provider_tier`
  - `bar_freshness`
  - `source_parity`
  - `trade_enablement`
  - optional `error`

## Validation

- `python -m pytest tests/test_data_integrity_stale_threshold.py -q` passed: 4 tests.
- `python -m py_compile api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py` passed.
- `ruff check api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py --config ruff.toml` passed.

## Next Action

- Continue with `P10-006`: add OpenAPI/schema regression tests for the expanded data-integrity contract.
