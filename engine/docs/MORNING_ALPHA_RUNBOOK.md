# JARVIS Morning Alpha Operational Runbook

## Scope

Morning Alpha is a deterministic research and paper-observation subsystem. It does **not** route live orders. Gate-v2 PASS is research certification only; paper-forward and live eligibility are separate promotion states.

## Local setup

1. Use Python 3.10+ in the JARVIS engine environment.
2. Install the repository requirements. Runtime adapters use `alpaca-py`; historical Parquet research uses DuckDB when configured; PostgreSQL journaling uses `psycopg2`.
3. Keep vendor SDK imports lazy so unit tests can run without credentials.
4. Run `PYTHONPATH=. pytest tests/morning_alpha -v` from `engine/` before any paper observation.

## Environment

Recommended variables (also listed in `engine/.env.morning-alpha.example`):

```text
MORNING_ALPHA_ENABLED=true
MORNING_ALPHA_PAPER_OBSERVATION=false
MORNING_ALPHA_ALPACA_API_KEY=<secret>
MORNING_ALPHA_ALPACA_SECRET_KEY=<secret>
MORNING_ALPHA_ALPACA_FEED=sip
MORNING_ALPHA_DATA_DIR=./data/morning_alpha
MORNING_ALPHA_POSTGRES_DSN=<dsn>
```

Do not place secrets in source control.

## PostgreSQL bootstrap

Apply `engine/morning_alpha/journal/schema.sql` to the configured Morning Alpha database before enabling persistence. The journal is append-only: candidate levels and strategy versions are never rewritten to improve historical results.

## Historical data

The Parquet provider reads from `${MORNING_ALPHA_DATA_DIR}/bars/*.parquet`. Queries must include `timestamp <= as_of`; future rows may exist in the store but must not influence a historical decision.

## Commands

```bash
python -m morning_alpha.cli scan --as-of 2026-09-15T13:00:00Z --provider alpaca --symbols SPY,QQQ,NVDA
python -m morning_alpha.cli audit --session 2026-09-15
python -m morning_alpha.cli research-trigger-lab --strategy relative_strength_breakout@1.0.0
```

`NO_TRADE` exits successfully. Notification systems should suppress delivery when the scan output is exactly `NO_TRADE`.

## Provider failures

- Missing symbol snapshot: reject the symbol and continue; do not infer values.
- Future timestamp: block the data and increment the point-in-time violation metric.
- Stale data: fail the universe eligibility gate.
- News/catalyst not verified by the scan timestamp: keep it unverified or exclude catalyst-dependent setup families.
- Live Alpaca/DuckDB dependency missing: fail that adapter explicitly; do not silently fall back to a different data source.

## Paper-only activation

Paper observation is allowed only after:

1. the setup family has adequate historical sample size or an approved sparse path;
2. chronological OOS/WFO exists;
3. cost/slippage tests exist;
4. canonical Gate-v2 passes;
5. parity tests confirm historical/live normalization; and
6. `MORNING_ALPHA_ENABLED=true` and `MORNING_ALPHA_PAPER_OBSERVATION=true` are explicitly configured.

No live broker mutation is implemented by Morning Alpha v1.

## Disable / rollback

1. Set `MORNING_ALPHA_ENABLED=false` or stop the Morning Alpha scheduler.
2. Set `MORNING_ALPHA_PAPER_OBSERVATION=false`.
3. Preserve the signal journal and research verdicts; do not delete failed observations.
4. Revert the feature branch/PR if code rollback is required.
5. Re-run the safe non-IB test suite before re-enabling.

## Monitoring

Watch:

- `morning_alpha_scan_duration_seconds`
- `morning_alpha_provider_staleness_seconds`
- `morning_alpha_candidates_total`
- `morning_alpha_qualified_total`
- `morning_alpha_no_trade_total`
- `morning_alpha_point_in_time_violations_total`
- `morning_alpha_audit_unverified_total`

Unexpected increases in staleness, PIT violations, or UNVERIFIED audit outcomes should pause paper observation until investigated.
