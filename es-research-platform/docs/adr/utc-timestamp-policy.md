# ADR: UTC timestamp policy

All internal timestamps are timezone-aware UTC values. Validation rejects naive datetimes at system boundaries, then normalizes aware datetimes to UTC. This avoids ambiguous session boundaries and reproducibility drift across WSL2, CI, and future compute environments.
