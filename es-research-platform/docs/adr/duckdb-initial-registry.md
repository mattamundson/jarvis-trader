# ADR: DuckDB as the initial registry

DuckDB is the initial experiment registry because it is local, simple to operate in WSL2, and strong enough for Phase 1 metadata queries. Registry access is isolated behind repository methods so domain code does not spread raw SQL throughout the application.
