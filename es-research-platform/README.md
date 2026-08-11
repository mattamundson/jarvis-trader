# ES Research Platform

Deterministic data and experiment foundation for research on S&P 500 E-mini futures (`/ES`).

The package owns data contracts, provenance, normalization, sessionization, bars, manifests, and
the experiment registry. Existing strategy simulation remains in `../engine/backtest`; the package
does not place orders or enable live trading. See [verification status](docs/verification-status.md)
for the precise implemented, tested, and unverified boundaries.

## Current status

| Capability | Status | Verification level |
|---|---|---|
| Typed contracts, canonical JSON, deterministic IDs | Implemented | Unit-tested |
| DuckDB experiment registry | Implemented | Integration-tested with real DuckDB |
| Synthetic trades → Parquet → sessions → 5-minute bars | Implemented | Executed and integration-tested |
| Immutable Databento DBN download adapter | Implemented | Unit-tested with an injected client; credentialed download unverified |
| Decoded Databento trades → silver Parquet and bars | Implemented | Integration-tested with vendor-shaped fixtures; real DBN unverified |
| Representative `/ES` session fixtures | Implemented | Unit-tested; not an authoritative exchange calendar |
| ThinkScript source catalog | Implemented | Repository inventory integration-tested; not strategy-equivalence proof |
| Strategy WFO and locked forward simulation | Existing engine integration | Focused engine-tested; not owned by this package |
| Real `/ES` bar parity against an independent aggregator | Not complete | Open acceptance gate |
| Event-level order-book simulation | Not implemented | Out of scope for the current milestone |
| Live trading | Not implemented | Explicitly out of scope |

## WSL2 setup

Use Windows 11 with WSL2 Ubuntu and Python 3.12+.

```bash
cd es-research-platform
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Install the optional Databento SDK only on machines that perform vendor downloads:

```bash
python -m pip install -e '.[dev,databento]'
```

DuckDB is a required runtime dependency for registry commands and registry integration tests. If dependency installation is blocked, contract and hashing tests can still run, but registry behavior is unverified until real DuckDB is installed.

## Checks

```bash
python -m ruff format .
python -m ruff check .
python -m mypy src
python -m pytest
```

## CLI

Initialize the registry:

```bash
python -m es_research registry init
```

Run the reproducibility demonstration:

```bash
python -m es_research demo reproducibility
```

Run the synthetic pipeline demonstration:

```bash
python -m es_research demo synthetic-pipeline
```

Download a small authorized Databento range into immutable bronze storage (timestamps must
include a UTC offset):

```bash
export DATABENTO_API_KEY='<your key>'
python -m es_research data ingest-databento \
  --dataset GLBX.MDP3 \
  --schema trades \
  --symbol ES.FUT \
  --start 2026-01-05T14:30:00+00:00 \
  --end 2026-01-05T14:35:00+00:00 \
  --output data/bronze/databento/es-trades.dbn.zst
```

The command refuses to overwrite an existing DBN file or sidecar. Dates above are an invocation
example only; use a range covered by your Databento entitlement. Do not commit the API key or
downloaded market data.

Normalize an immutable DBN file using separately versioned symbology and session inputs:

```bash
python -m es_research data normalize-databento \
  --input data/bronze/databento/es-trades.dbn.zst \
  --instrument-map config/databento-instruments.json \
  --sessions config/es-sessions.json \
  --output-dir data/silver/databento/es-trades
```

The instrument map is a JSON object such as `{"12345":"ESH6"}`. The sessions file is a JSON
array of `SessionCalendar` objects with timezone-aware ISO-8601 timestamps. The command validates
and hashes both inputs, decodes DBN through the optional Databento SDK, writes and reads back the
versioned silver Parquet file, assigns sessions, builds and validates five-minute bars, and writes
`acceptance_report.json` with source, reference-data, silver-row, and bar hashes. Session files
must come from an authoritative vendor or exchange calendar and must be retained with the report.

Catalog the repository's ThinkScript sources without executing or porting strategy logic:

```bash
python -m es_research catalog thinkscript \
  --source-dir ../thinkorswim-scripts \
  --output manifests/thinkscript-catalog.json
```

The catalog validates every registry script, documentation path, and declared duplicate, then
records SHA-256 hashes, statuses, layers, parameters, and Python-counterpart references. It is a
location-independent provenance artifact—not evidence that a ThinkScript is a complete strategy,
that an existing Python counterpart is equivalent, or that either has passed out-of-sample tests.
New ThinkScript implementation and strategy promotion remain gated on credentialed real-data
acceptance and independent bar-value validation. Existing engine study runners are integration
tools, not evidence that the package's real-data gate has passed.

The reproducibility demo constructs the same synthetic experiment twice and fails if deterministic hashes or identifiers differ. The synthetic pipeline demo writes normalized Parquet, reads it back, assigns sessions, builds 5-minute OHLCV bars, validates outputs, and prints deterministic hashes, and writes a deterministic `pipeline_report.json`. These demos use synthetic metadata and artificial engineering fixtures, not fabricated market data.

## Architecture decisions

Architecture decision records are stored in `docs/adr/`:

- UTC timestamp policy
- Immutable bronze data
- Deterministic experiment hashing
- DuckDB as the initial registry
- Separation of screening from realistic simulation

## Foundation notes

- The registry requires real DuckDB; there is no local SQLite-backed `duckdb` shim.
- Registry tables preserve full JSON payloads and expose queryable columns for common research dimensions such as strategy hash, manifest hash, status, simulation level, PnL, drawdown, and result timestamp.
- Deterministic candidate and experiment identifiers are created by shared identity helpers instead of ad hoc demo code.

## Data vertical slice

The first Phase 2 vertical slice adds deterministic synthetic trade events, normalized trade rows with versioned PyArrow Parquet IO, session assignment, 5-minute OHLCV bar construction, and validation tests. The normalized Parquet reader rejects missing schema-version metadata or physical schema drift.

The next boundary is also implemented without embedding credentials: `ingestion.databento`
accepts an injected Databento historical client, writes the original compressed DBN response
to immutable bronze storage, and records a SHA-256 sidecar. `normalization.databento` converts
decoded trade records to the vendor-neutral silver contract using an explicit instrument
mapping and DBN fixed-price scale. Install the `databento` extra and construct the authenticated
client outside the domain layer; never commit API keys.

Representative `/ES` calendar fixtures cover overnight open, RTH, the UTC shift across US DST,
Friday close, a closed date, and an early-close shape. They are deterministic engineering test
fixtures—not an authoritative exchange calendar. Production jobs must persist the vendor or
exchange calendar source and version used for each dataset.

The package does not implement strategy signals or make performance claims. The adjacent engine
contains screening and locked-forward runners; their outputs remain research evidence and are not
investment recommendations or authorization to trade.

## Next milestone

1. Validate the bronze adapter against a small, user-authorized Databento DBN download.
2. Persist vendor symbology and authoritative exchange session definitions with source hashes.
3. Decode that DBN file into the versioned silver Parquet schema and compare row counts,
   timestamp ranges, prices, quantities, and hashes with the Databento metadata.
4. Validate 5-minute bars against independently aggregated values before adding new strategy
   families or treating engine backtests as accepted platform experiments.
