# JARVIS Morning Alpha Operational Runbook

## Scope

Morning Alpha is a deterministic research and paper-observation subsystem. It does **not** route live orders. Gate-v2 PASS is research certification only; paper-forward and live eligibility are separate promotion states.

## Local setup

1. Use Python 3.10+ in the JARVIS engine environment.
2. Install the repository requirements. Runtime adapters use `alpaca-py`; historical Parquet research uses DuckDB when configured; PostgreSQL journaling uses `psycopg2`.
3. Keep vendor SDK imports lazy so unit tests can run without credentials.
4. Run `pytest tests/morning_alpha -v` from `engine/` before any paper observation.

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
6. `MORNING_ALPHA_PAPER_OBSERVATION=true` is explicitly configured.

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

## Research-data readiness gate

Before running any historical campaign, build artifact receipts, generate `${MORNING_ALPHA_DATA_DIR}/research_manifest.json`, and validate it. Example:

```bash
python -m morning_alpha.cli research-receipt-create \
  --data-root ./data/morning_alpha \
  --kind universe_membership \
  --path evidence/universe.csv \
  --provider YOUR_PROVIDER \
  --row-count 100000 \
  --symbol-count 1200 \
  --point-in-time \
  --json

python -m morning_alpha.cli research-manifest-build \
  --data-root ./data/morning_alpha \
  --json

python -m morning_alpha.cli research-data-check --data-root ./data/morning_alpha --json
python -m morning_alpha.cli research-campaign-plan --json
```

Each receipt stores the artifact kind, provider, relative path, SHA-256, row/symbol counts, coverage timestamps, and point-in-time assertion. Manifest v1.1 readiness recomputes the artifact hashes and fails closed if a receipt is missing, the file is missing, or bytes have changed.

`research-data-check` exits `0` only when the dataset satisfies the frozen v1 evidence contract. Exit `2` means the dataset is not research-ready and the campaign must not run.

The manifest must prove, at minimum:

- provider/source lineage;
- at least 500 daily symbols;
- at least 100 intraday symbols;
- at least 8 years of daily history;
- point-in-time universe membership;
- delisted-symbol coverage;
- corporate-action handling;
- historical sector mappings;
- earnings-event data;
- macro/regime context;
- premarket/intraday bars; and
- timezone-aware coverage timestamps.

The presence of Parquet files alone is only a file-stage smoke test and is never sufficient for an edge claim.
