# PASS50 - Data Integrity Provider Metadata

## Scope

- Completed `P10-007`.
- Added optional market-data provider metadata settings:
  - `MARKET_DATA_ACTIVE_PROVIDER`
  - `MARKET_DATA_PRIMARY_PROVIDER`
  - `MARKET_DATA_FALLBACK_PROVIDERS`
- Wired `/system/data-integrity` `provider_tier` to report configured metadata as `known` and preserve `unknown` when metadata is absent.

## Evidence

- `provider_tier` remains explicit and non-green by default:
  - `status: unknown`
  - `reason: provider metadata not wired`
- When metadata is configured, `provider_tier` reports:
  - `status: known`
  - `active`
  - `primary`
  - `fallbacks`

## Validation

- `python -m pytest tests/test_data_integrity_stale_threshold.py -q` passed: 6 tests.
- `python -m py_compile config.py api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py` passed.
- `ruff check config.py api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py --config ruff.toml` passed.

## Next Action

- Continue with `P10-008`: align sidebar navigation with the Command Center consolidation policy.
