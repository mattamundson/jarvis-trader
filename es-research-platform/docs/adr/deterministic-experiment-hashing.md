# ADR: Deterministic experiment hashing

Strategy definitions, configurations, and data manifests use canonical JSON with sorted keys and compact separators before SHA-256 hashing. Equivalent dictionaries therefore hash identically, while meaningful configuration changes produce new hashes.
