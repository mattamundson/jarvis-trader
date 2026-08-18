# ADR: Preserve Databento DBN at the bronze boundary

**Status:** Accepted

Databento responses are stored as immutable compressed DBN files before decoding. Each
artifact receives a deterministic JSON sidecar containing the complete request, byte count,
and SHA-256 digest. Existing paths are never overwritten, and downstream normalization reads
decoded records into the vendor-neutral `TradeEvent` contract. This keeps vendor schema and
symbology decisions out of silver data while preserving the exact source bytes for replay.
