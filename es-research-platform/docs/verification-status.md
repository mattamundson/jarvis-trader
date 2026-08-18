# Verification status and scope boundaries

This document distinguishes implemented code from observed runtime behavior. A successful lint,
type-check, build, or import is not evidence that a data pipeline produced numerically correct
market data.

## Verification levels

| Level | Meaning |
|---|---|
| Implemented | Code exists, but the relevant path may not have executed. |
| Static-checked | Formatting, linting, or typing passed. |
| Unit-tested | Isolated behavior passed controlled tests. |
| Integration-tested | Multiple real components executed together with controlled fixtures. |
| Executed | The actual CLI or runtime path ran and its output was observed. |
| Data-accepted | Output values were reconciled against an independent authoritative source. |

Only **data-accepted** supports a claim that real normalized records or bars are numerically
correct. No `/ES` vendor dataset has reached that level in this package yet.

## Package boundary

`es-research-platform` owns:

- Domain data contracts and UTC validation.
- Canonical serialization and deterministic identities.
- Immutable bronze artifact handling.
- Databento record normalization.
- Versioned silver Parquet IO.
- Session assignment and deterministic bar construction.
- Data manifests and acceptance reports.
- DuckDB experiment metadata.
- Source cataloging for future strategy research.

It does not own:

- Broker connectivity or order submission.
- Live or paper-trading authorization.
- Existing strategy implementations in `engine/backtest`.
- Existing engine candidate promotion policy.
- Event-level exchange queue simulation.
- Claims of profitability or investment recommendations.

## Verified locally and enforced by focused CI checks

- Equivalent dictionaries produce identical hashes.
- Naive datetimes are rejected at model boundaries.
- Registry schema initialization is idempotent.
- Registry records round-trip through real DuckDB.
- Versioned normalized rows round-trip through real PyArrow Parquet.
- Synthetic pipeline reruns produce identical logical hashes.
- Databento-shaped decoded records normalize, sessionize, and aggregate into expected bars.
- The ThinkScript registry resolves every declared source, documentation file, and duplicate.
- Focused engine tests cover explicit execution costs, KAMA parity, cutoff exclusion, and locked
  parameter validation.

## Implemented but not yet accepted with real vendor data

- Authenticated Databento download.
- DBN decoding against a user-entitled `/ES` response.
- Databento instrument mapping against retained vendor metadata.
- Authoritative CME session and holiday ingestion.
- Tick-size reconciliation for every normalized trade.
- Independent bar-by-bar parity over a real session.
- Roll-calendar and continuous-contract construction.

## Next acceptance gate

The next phase must stop after one small, authorized Databento slice and prove:

1. Bronze bytes and sidecar hashes reproduce.
2. Vendor symbology resolves every instrument.
3. Decoded row counts and timestamp bounds reconcile.
4. Silver Parquet regenerates identically.
5. Canonical and independently aggregated bars match exactly.
6. Hand-selected bars match their contributing source trades.

Until all six checks pass, real-data processing remains **unverified**, even when synthetic and
fixture-based tests are green.
