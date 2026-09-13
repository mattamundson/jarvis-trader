# Prediction-market backtest adapter evidence checklist

Status: research/specification only. No runtime, broker, risk, kill-switch, environment, or order-routing behavior is changed by this document.

Source mined

- Reference repo: `mattamundson/prediction-market-backtesting`
- Reference commit: `736e5dcbb1c065f24a28101328a469823b27f4e2`
- Source role: fork of NautilusTrader with Polymarket and Kalshi adapters, prediction-market examples, and backtest utilities.
- Selected evidence files:
  - `nautilus_pm/nautilus_trader/adapters/prediction_market/backtest_utils.py`
  - `nautilus_pm/tests/unit_tests/adapters/prediction_market/test_backtest_utils.py`
  - `nautilus_pm/examples/backtest/prediction_markets/_polymarket_single_market_runner.py`
  - `nautilus_pm/examples/backtest/prediction_markets/kalshi_ema_bars.py`
  - `nautilus_pm/nautilus_trader/adapters/polymarket/fee_model.py`
  - `nautilus_pm/nautilus_trader/adapters/kalshi/market_selection.py`
  - `nautilus_pm/crates/adapters/polymarket/README.md`

Why this matters for JARVIS

Prediction markets are binary-settlement instruments with probability-like prices, explicit resolution events, venue-specific fees, and event metadata. That makes them useful as a reference for JARVIS research tooling, but dangerous to blend directly into the futures/options execution spine. The import target is not a venue adapter. The import target is an evidence contract for any future event-market research/backtest adapter.

The reusable patterns are:

1. Normalize all timestamps to UTC before replay.
2. Treat price as bounded probability and clip/validate to `[0, 1]`.
3. Separate market-data loading from deterministic replay catalogs.
4. Keep Polymarket, Kalshi, and futures/options schemas isolated.
5. Mark unresolved markets as incomplete instead of fabricating outcomes.
6. Include settlement-aware PnL and venue fee modeling in every backtest claim.
7. Export chart/review artifacts without making them proof of edge.

Hard safety boundary

- Do not wire Polymarket/Kalshi execution into JARVIS paper or live order routing from this checklist.
- Do not change `engine/config.py`, `engine/risk/`, `paper_config.py`, `.env`, broker routing, kill-switches, active instrument gates, PM2, or order behavior without a dedicated `[safety-review]` PR.
- Event-market prices may inform research, journaling, or sentiment context only. They must not auto-authorize futures/options entries.
- Any future implementation must default to deterministic replay/offline mode and must prove no external order API is called in tests.

Adapter acceptance gates

A future JARVIS event-market backtest adapter is not acceptable until it satisfies all gates below.

1. Source provenance gate

Required fields per dataset or market:

- `source_repo_or_api`
- `source_commit_or_api_version`
- `venue` (`polymarket`, `kalshi`, or another explicit value)
- `market_id`
- `market_slug_or_ticker`
- `outcome_token_or_side`
- `resolution_status`
- `resolution_value`
- `first_event_ts_utc`
- `last_event_ts_utc`
- `ingested_at_utc`
- `raw_artifact_sha256`

Fail closed when any source artifact lacks venue, market ID, timestamp range, or artifact hash.

2. Time normalization and replay determinism gate

Reference behavior from `backtest_utils.py`: timestamp-like values are coerced to UTC; nanosecond timestamps are accepted; duplicate timestamps keep the last point; chart/replay output can resample with last observation in bucket.

JARVIS rule:

- Convert every market-data event to UTC before writing a replay artifact.
- Reject or quarantine records with unparseable timestamps.
- Sort by `(event_ts_utc, sequence_or_source_offset)` before replay.
- Store a stable `replay_id = sha256(source_hash + adapter_version + normalized_schema_version)`.
- Re-running the same replay must produce identical order, count, price series, and hash.

Minimum local verification for implementation:

- Fixture with mixed timezone strings, nanosecond integer timestamps, duplicates, and malformed timestamps.
- Expected output has monotonic UTC timestamps, deterministic duplicate handling, and explicit quarantine count.

3. Probability/price sanity gate

Reference behavior: `_probability_frame()` clips `market_probability` to `[0, 1]`. Kalshi helpers normalize cent fields by dividing values `>= 1.0` by `100.0` before accepting prices inside `(0, 1)`.

JARVIS rule:

- Keep raw venue price and normalized probability as separate fields.
- Reject impossible normalized prices outside `[0, 1]` unless the adapter explicitly documents a cent-to-probability conversion.
- Track `bid`, `ask`, `mid`, `last`, and `spread` separately when available.
- Never infer edge from `last` alone when bid/ask data exists.

4. Resolution/outcome gate

Reference behavior: `infer_realized_outcome()` checks `result=yes/no`, numeric `settlement_value` or `expiration_value`, token `winner` flags, and special `is_50_50_outcome` markets. If no resolution is found, Brier outcome series is empty rather than invented.

JARVIS rule:

- Unresolved markets are allowed for forward-tracking dashboards, but not for closed backtest performance claims.
- Outcome values must be one of `0.0`, `0.5`, `1.0`, or `null` with an explicit `resolution_status`.
- A backtest report citing realized PnL, Brier score, hit rate, or calibration error must include the number of resolved, unresolved, and ambiguous markets.
- Ambiguous or partial markets get a separate bucket and must not be silently pooled with binary outcomes.

5. Settlement-aware PnL gate

Reference behavior: `compute_binary_settlement_pnl()` marks remaining open quantity to the resolved outcome and subtracts commissions.

JARVIS rule:

- Closed-market PnL must include both fill-level cashflows and terminal settlement value for any open shares/contracts.
- Reports must show two numbers when applicable: mark-to-market PnL at the last observed price and settlement PnL at the resolved outcome.
- Strategy comparison must specify which PnL basis is ranked.
- Any claim about edge after fees must state the fee model and whether maker/taker/settlement costs were included.

6. Fee/slippage gate

Reference behavior: `PolymarketFeeModel` applies taker fee formula `fee = qty * feeRate * p * (1 - p)` and returns zero when taker fee basis points are unavailable or non-positive. The source README separates CLOB REST, CLOB WebSocket, and Gamma data surfaces.

JARVIS rule:

- Fee model must be venue-specific and versioned.
- Missing fee data must be labeled `fee_unknown`, not silently assumed to be free unless the venue contract says so and a source is cited.
- Slippage must be modeled from order-book depth or a documented fallback ladder, not from candle close-to-close moves.
- Research reports must include gross PnL, fees, slippage, and net PnL as separate fields.

7. Venue schema isolation gate

Reference behavior: Polymarket runners use `POLYMARKET_VENUE`, `USDC_POS`, token index, market slug, and Polymarket fee model. Kalshi examples use `KALSHI`, market ticker, USD base currency, and a local Parquet catalog.

JARVIS rule:

- Do not create a generic `prediction_market` schema that hides venue-specific fields needed for replay and audit.
- Use a common envelope plus venue-specific payload:
  - `common`: time, venue, market ID, outcome, price, side, quantity, source hash.
  - `polymarket`: slug, token index, CLOB order/trade fields, USDC denomination, Gamma metadata.
  - `kalshi`: ticker, category, close time, cents/dollars normalization, USD denomination.
- Cross-venue analytics must operate on normalized read models, not by mutating raw venue payloads.

8. Deterministic catalog gate

Reference behavior: `kalshi_ema_bars.py` fetches bars, writes instrument and bars into a local `ParquetDataCatalog`, then backtests against that catalog.

JARVIS rule:

- Research backtests must load from immutable local artifacts after ingestion.
- API pulls belong to ingestion jobs; backtest jobs consume stamped data catalogs.
- A report must record catalog path, catalog hash, adapter version, and run config hash.
- No backtest may depend on live API responses during the scoring phase.

9. Liquidity/minimum-sample gate

Reference behavior: Polymarket runners skip markets with too few trades or inadequate price range before running the strategy.

JARVIS rule:

- Every event-market strategy must set minimum thresholds for trades, active duration, spread, depth, and non-zero price range.
- Thresholds must be declared before the run and printed in the report.
- Markets failing thresholds are exclusions, not losses or wins.
- Exclusion counts and reasons must be included in aggregate performance.

10. Calibration/evaluation gate

Reference behavior: `build_brier_inputs()` creates rolling user probabilities and compares them against market probabilities and resolved outcomes when available.

JARVIS rule:

- Probability strategies must report calibration quality, not only PnL.
- Minimum metrics: Brier score, Brier advantage versus market probability, log loss where defined, resolved-market count, unresolved-market count, and calibration by probability bucket.
- A strategy with positive PnL but worse-than-market calibration is a trading tactic, not a forecasting edge; label it accordingly.

JARVIS implementation candidate

The next safe implementation is a docs/tests-only scaffold, not an adapter:

- `engine/research/event_markets/schema.py` or equivalent dataclass/Pydantic model for normalized replay records.
- Fixture-only tests for UTC normalization, price bounds, venue-specific payload separation, resolution inference, settlement PnL, and deterministic replay hash.
- No network calls.
- No broker or order-router imports.
- No runtime settings edits.

Minimum PR evidence for that implementation:

- `env -u PYTHONPATH engine/.venv/Scripts/python.exe -m pytest <new_fixture_tests> -q`
- A source-provenance note pointing to `mattamundson/prediction-market-backtesting` commit `736e5dcbb1c065f24a28101328a469823b27f4e2`.
- Forbidden-surface grep showing no changes to config, risk, broker routing, `.env`, PM2, kill switch, or active instrument gates.

Relationship to existing JARVIS docs

This checklist extends `docs/research/polymarket-probability-orderbook-risk-checklist.md` by moving from live/order-book risk controls to offline deterministic backtest/replay controls. The two documents should stay separate:

- Polymarket probability/order-book risk checklist: live data and order-book sanity controls.
- Prediction-market backtest adapter checklist: deterministic replay, resolution-aware scoring, catalog provenance, and venue schema boundaries.

Decision

Keep `prediction-market-backtesting` as a read-only reference fork. Mine its adapter/replay/settlement patterns into JARVIS research docs and tests. Do not merge the Nautilus fork, venue adapters, auth flows, or live execution code into JARVIS unless a later scoped implementation proves isolated offline replay first and a separate `[safety-review]` PR explicitly approves any execution-adjacent surface.
