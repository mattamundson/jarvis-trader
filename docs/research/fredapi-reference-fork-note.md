# JARVIS Research Note — fredapi (mattamundson/fredapi)

**Source:** `mattamundson/fredapi`, default branch `master`, 14 files, NOT a fork, **archived: true** (verified this run), private: yes, pushed 2026-04-22.
**What it is:** Python API wrapper for FRED (Federal Reserve Economic Data) and ALFRED (Archival FRED). This is the original `mortada/fredapi` repo, forked/imported by Amo and already archived.

## Reusable patterns for JARVIS

### 1. FRED/macro regime-context spec (already in audit backlog)
- fredapi is the canonical Python wrapper for FRED. The JARVIS add is the **macro/FRED regime-context spec**: how JARVIS consumes macro series (e.g. rate decisions, CPI, unemployment, yield curve) as regime-context features, with explicit rules:
  - Macro data is a **regime filter/context feature only** — it does not directly place trades.
  - Freshness gate: macro releases have known schedules; JARVIS must not act on stale or not-yet-released data.
  - Paid/free feed adapter abstraction: FRED has an API key; treat it as one adapter among possibly several, with the same abstraction JARVIS uses for market data.
- This is the backlog item "macro/FRED regime-context spec."

### 2. Archived → provenance recorded
- fredapi is already archived (`isArchived: true`, verified this run). Its value to JARVIS is as a reference for the FRED adapter pattern, not as a live dependency. Provenance: the FRED regime-context spec should cite fredapi as the reference for the FRED API shape, but JARVIS should not depend on the archived fork's code directly.

### What NOT to import
- Do not vendor fredapi's code into JARVIS (it's archived, private, and a third-party wrapper). Use it as the spec reference only.
- No execution wiring; no risk limit changes.

## Recommended JARVIS doc add (small, doc-only)
- `docs/research/macro-fred-regime-context-spec.md` — FRED/macro as regime-context feature only, freshness gate, adapter abstraction, and the fredapi provenance note.

**Safety class:** S0 — doc-only research note. No code, no config, no execution wiring.
