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

The demo constructs the same synthetic experiment twice and fails if deterministic hashes or identifiers differ. It stores only synthetic metadata/results used for reproducibility validation, not fabricated market data.

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

## Phase 2 scope

The next vertical slice should add synthetic event data, normalized Parquet, session assignment, 5-minute bars, and validation tests. Real Databento data should wait until the following phase.
