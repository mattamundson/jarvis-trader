# ES Research Platform

Phase 1 foundation for a research-grade S&P 500 E-mini futures (`/ES`) strategy research and backtesting platform.

This milestone intentionally implements only repository structure, data contracts, deterministic hashing, reproducibility manifests, a DuckDB experiment registry, CLI commands, and tests. It does not download market data, compute indicators, run strategies, backtest, use GPUs, distribute workloads, or trade live.

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
ruff format .
ruff check .
mypy src
pytest
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

The reproducibility demo constructs the same synthetic experiment twice and fails if deterministic hashes or identifiers differ. The synthetic pipeline demo writes normalized Parquet, reads it back, assigns sessions, builds 5-minute OHLCV bars, validates outputs, and prints deterministic hashes, and writes a deterministic `pipeline_report.json`. These demos use synthetic metadata and artificial engineering fixtures, not fabricated market data.

## Architecture decisions

Architecture decision records are stored in `docs/adr/`:

- UTC timestamp policy
- Immutable bronze data
- Deterministic experiment hashing
- DuckDB as the initial registry
- Separation of screening from realistic simulation

## Phase 1 hardening notes

- The registry requires real DuckDB; there is no local SQLite-backed `duckdb` shim.
- Registry tables preserve full JSON payloads and expose queryable columns for common research dimensions such as strategy hash, manifest hash, status, simulation level, PnL, drawdown, and result timestamp.
- Deterministic candidate and experiment identifiers are created by shared identity helpers instead of ad hoc demo code.

## Phase 2 data vertical slice

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

This slice still does not implement strategy signals, backtesting, performance claims, or investment recommendations.

## Next milestone

1. Validate the bronze adapter against a small, user-authorized Databento DBN download.
2. Persist vendor symbology and authoritative exchange session definitions with source hashes.
3. Decode that DBN file into the versioned silver Parquet schema and compare row counts,
   timestamp ranges, prices, quantities, and hashes with the Databento metadata.
4. Validate 5-minute bars against independently aggregated values before introducing any
   features, strategy rules, or backtesting.
