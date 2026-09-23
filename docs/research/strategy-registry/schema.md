# Strategy registry schema

**Status:** v1, 2026-09-12. Documentation + schema only; no engine code, no config, no
trading behavior.

The strategy registry is the durable, machine-readable ledger of every candidate strategy
in the JARVIS research loop. It ties together what the prose docs describe
(`strategy-research-operating-model.md`) into one record-per-strategy file with a fixed
field set, so that provenance, evidence paths, and promotion state never drift apart.

## File layout

```text
docs/research/strategy-registry/
  README.md            — how to use the registry (this set of docs)
  schema.md            — field definitions (this file)
  schema.json          — JSON Schema (draft 2020-12) for registry entry files
  entries/             — one JSON file per strategy_id
    <strategy_id>.json
  seed/
    2026-09-12-initial-seed.md — provenance note for the initial seeded entries
```

## Record format

Each entry is one JSON object validated against `schema.json`. Keys are fixed; unknown
keys are rejected (`additionalProperties: false`) so drift is caught at review time.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | yes | Always `"1.0"` for this schema. |
| `strategy_id` | string | yes | Stable unique ID. Convention: `<SYMBOL>_<slug>` lowercased, e.g. `spy_atrband_breakout_rank1`, `mes_sma50200_atr`. Never reused for a new strategy — supersede with a new ID and link `supersedes`. |
| `name` | string | yes | Human-readable name. |
| `source` | object | yes | Provenance: `type` (one of `x-bookmark-scan`, `imported-repo`, `internal-idea`, `llm-generated`, `adapted`, `human`), `repo_or_note` (GitHub repo, note path, or prompt ref), `url` (optional), `imported_via` (optional PR number). |
| `hypothesis` | string | yes | One or two falsifiable sentences. "Trend-following on MES works" is too vague; "MES reverts after a >=2×ATR intraday range extension" is acceptable. |
| `asset_class` | string | yes | `equity-index`, `future`, `option`, `forex`, `crypto`, `prediction-market`. |
| `symbols` | string[] | yes | Ticker(s) the strategy is defined against. |
| `timeframe` | string | yes | Bar timeframe of the rules, e.g. `1h`, `daily`, `monthly`, `per-night`. |
| `data_sources` | object[] | yes | One entry per feed: `feed` (`databento`, `ibkr`, `yfinance`, `fred`, `csv`), `adjusted` (bool), `timezone`, `range_start`, `range_end`. |
| `feature_set` | string[] | yes | Named features/indicators used by the rules. |
| `rules` | object | yes | `entry`, `exit`, `position_sizing`, `risk_limits`, `fees_and_slippage_model`. Each a short string; the full logic lives in code, the registry records the *intent* so a reviewer can match code to claim. |
| `windows` | object | yes | `train`, `test`, `walk_forward` — each `{start, end}` or `null` when not yet run. `walk_forward` may additionally carry `config`. |
| `metrics` | object | no | Reported results from the latest run: `net_pnl`, `cagr`, `max_drawdown`, `sharpe`, `sortino`, `profit_factor`, `trade_count`, `win_rate`, `exposure`, `fees_slippage_assumption`, `regime_split`, `parameter_sensitivity`, `monte_carlo`. All optional individually, but at least one must be present once a backtest exists. |
| `gate_verdict` | object | no | Latest gate result: `gate` (e.g. `gate-v2`), `verdict` (`PASS`, `FAIL`, `UNSCORED`, `UNRUN`, `INSUFFICIENT_SAMPLE`), `core_verdict`, `alt_verdict`, `reasons[]` (copied verbatim from the card/verdict file), `as_of` (optional snapshot timestamp/note for verdicts sourced from docs rather than a committed card), `evidence_path` (path to the `.gate_v2.json` card or engine verdict file). |
| `promotion_state` | string | yes | One of the lifecycle states below. This is the only field that changes as the strategy moves through the loop. |
| `known_failure_modes` | string[] | no | Failure modes already observed or suspected. |
| `evidence_paths` | string[] | no | Repo-relative or absolute paths to artifacts: backtest outputs, gate cards, notebooks, journal entries, PR links. |
| `owner` | string | no | Who is driving this candidate (default: `amo`). |
| `supersedes` | string | no | Previous `strategy_id` if this record replaces one. |
| `updated` | string | yes | `YYYY-MM-DD` of the last registry edit. |

## Lifecycle states (`promotion_state`)

```text
idea -> data-contract -> backtested -> robustness -> walk-forward -> paper-shadow -> promoted | rejected | archived
```

- `idea` — hypothesis recorded, no data contract yet.
- `data-contract` — data sources, range, and adjustment policy pinned; backtest not yet run.
- `backtested` — baseline backtest exists with the metrics floor partially met.
- `robustness` — parameter sensitivity, regime split, and multiple-testing checks run.
- `walk-forward` — WFO/OOS validation complete.
- `paper-shadow` — running in paper with drift checks; not yet authorized for routing.
- `promoted` — passed all gates and the explicit promotion record; authorized path exists.
- `rejected` — failed a gate or operator decision; reasons in `gate_verdict.reasons` / `known_failure_modes`.
- `archived` — no longer under consideration; retained for provenance.

**Hard rule:** a record may only move to `promoted` when `gate_verdict.verdict == "PASS"`
*and* `evidence_paths` includes the gate card *and* a PR or decision-ledger reference.
Anything touching execution, risk, kill switch, broker adapters, or active instrument
gates additionally requires a `[safety-review]`-tagged PR (see root `CLAUDE.md`).

## Seed entries

`entries/` is seeded on 2026-09-12 from the seven committed `docs/research/*.gate_v2.json`
cards (all `FAIL` verdicts, x-bookmark edge-scan origin) plus the MES SMA(50,200)
golden-cross trend strategy whose rules live in `engine/backtest/trend_signals.py`
(WFO-champion params from `engine/backtest/paper_config.py`). Seed provenance:
`seed/2026-09-12-initial-seed.md`.
