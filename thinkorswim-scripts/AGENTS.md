# ThinkScript Feature-Integrity Agent Rules

These rules apply to work under `thinkorswim-scripts/` and supplement the root `AGENTS.md` / `CLAUDE.md`.

## Safety boundary

- Treat every legacy ThinkScript as a **research source**, not production truth.
- Do not modify a legacy `.ts` formula merely to make it agree with the Python engine.
- Do not mark a feature `live_allowed`, `paper_allowed`, parity `passed`, or causal `safe` solely because code compiles or a chart looks correct.
- Do not change live strategy parameters, broker settings, risk limits, or execution configuration from a source-integrity task.
- Any proposed production promotion must remain a separate human-reviewed change.

## Required distinctions

Keep these statuses independent:

1. **Source integrity** — do we understand what the source actually computes?
2. **Causal integrity** — could the value have been known at the decision timestamp?
3. **Parity** — does a named Python variant reproduce the named source variant?
4. **Statistical evidence** — does the feature add validated OOS value?
5. **Deployment** — is it eligible for research, paper, or live use?

`ported != parity != causal != validated != live`.

## Future/reference review

Before translating a ThinkScript into a research feature, scan/review at least:

- negative indices (`[-1]`, `[-2]`, ...)
- `GetTime()[-1]`, `GetMonth()[-1]`, `GetYear()[-1]`
- `HighestAll`, `LowestAll`, `InertiaAll`
- secondary aggregation / developing higher-timeframe semantics
- `TimeProfile` / `VolumeProfile` data semantics
- hard-coded exchange calendar dates
- external-symbol dependencies
- foreign syntax such as `ta.*`

A static finding is a **review flag**, not automatic proof of leakage. Document the causal interpretation explicitly.

## Parity workflow

For each source-derived formula:

1. preserve the legacy/source-reference implementation under a versioned name;
2. preserve any cleaner/standard implementation under a different versioned name;
3. build deterministic Golden Vector fixtures;
4. prove equality where parity is intended;
5. prove non-equality where two variants are intentionally distinct;
6. never silently replace historical formula semantics.

## Research evidence

Do not claim alpha from parity tests. Parity establishes implementation identity only.
Statistical promotion belongs to the validation/Judge pipeline and must use point-in-time data and locked out-of-sample evidence.
