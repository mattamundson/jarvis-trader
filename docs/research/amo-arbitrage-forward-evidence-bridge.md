# Amo Arbitrage forward-evidence bridge contract

Status: research/control artifact only. `amo-arbitrage` remains a separate
product. This wave does not import execution code, does not connect data feeds,
and does not change live/paper trading behavior in JARVIS.

No live trading config, paper trading config, risk limits, kill-switch state,
broker routing, API keys, `.env` files, PM2, active instrument gates, scheduled
tasks, or order behavior are changed.

## Source mined

- Source repo: `mattamundson/amo-arbitrage`
- Source commit reviewed locally: `95da4cd`
- Source role: separate commodity/arbitrage product, not a repo to fold into
  `jarvis-trader`.
- Selected files reviewed locally:
  - `backend/preregistration/seasonal_family_2026-06-16.md`
  - `backend/pipelines/forward_test.py`
  - `backend/pipelines/feed_reconciliation.py`
  - `backend/pipelines/data_quality.py`
  - `backend/docs/RELIABILITY.md`

## Coverage proof

Prior waves already covered generic backtest critique, strategy registry, macro
regime context, event-market replay, and agentic research controls. `amo-arbitrage`
This repo adds a non-duplicative lesson that is directly useful to JARVIS: **historical
screens are not promotions**; forward evidence, pre-registration integrity,
single-writer feed provenance, and data-quality gates must be first-class fields
before a separate-product pattern can influence the trading system.

This bridge encodes two plain rules for JARVIS: historical screens are not promotions, and `amo-arbitrage` stays a separate product.
This is a bridge contract, not a migration. `amo-arbitrage` remains a separate
product; JARVIS can borrow evidence patterns but not execution code or product
assumptions.

## Transferable controls

1. Pre-registration integrity: freeze the candidate family before evaluating
   p-values, and treat any post-hoc family edit as a new freeze.
2. Multiple-testing honesty: small family BH-FDR is only legitimate when the
   family membership is economically pre-specified, not selected from observed
   p-values.
3. Historical screen vs promotion: even a strong historical screen stays
   non-binding until forward evidence accumulates out of sample.
4. Distinct exploratory labels: evidence-only streams need labels that cannot
   collide with validated strategy rows.
5. Zero-exposure exploratory streams: exploratory evidence can collect returns
   while staying unvalidated and unsized.
6. Single-writer feed invariant: a critical market-data table must have exactly
   one writer; if ownership moves, old and new writers change in the same scoped
   decision.
7. Backfill ledger immutability: bridge/backfilled bars should be snapshotted
   before authentic feed overwrite, then reconciled rather than silently trusted.
8. Data quality fails closed: future-dated rows, missing existence checks, stale
   freshness, and parse failures should block evidence promotion.
9. Weekend/business-day freshness: calendar age is not always the correct SLA for
   weekday market data.
10. Product boundary: commodity/arbitrage lessons can enrich JARVIS evidence
    contracts only through explicit adapters and promotion gates.

## JARVIS forward-evidence bridge requirements

Any future JARVIS adapter that imports a pattern from `amo-arbitrage` must attach
a bridge evidence object with:

- `source_repo` and `source_commit`.
- `product_boundary = separate_product_bridge_only`.
- `pre_registration.freeze_hash` and immutable family members when applicable.
- `multiple_testing.protocol`, family size, q-value, and missing-member padding.
- `historical_screen.is_binding = false` unless a fresh, pre-registered protocol
  says otherwise.
- `forward_evidence.out_of_sample_required = true`.
- `exploratory_streams.zero_exposure_required = true` for unvalidated variants.
- `feed_ownership.single_writer_required = true` plus owner/migration notes.
- `data_quality.fail_closed_checks` for freshness, future dates, existence, and
  parse errors.
- `blocked_influence` explicitly naming registry promotion, runtime routing, risk
  limits, kill-switch, `.env`, PM2, and broker/order behavior.

## Allowed next steps

- Add fixture-only validators for bridge evidence objects.
- Use pre-registration/freeze concepts in research docs and dashboards.
- Add offline reports that compare historical-screen and forward-evidence status.

## Blocked without a separate `[safety-review]` PR

- Migrating `amo-arbitrage` execution code into JARVIS.
- Connecting JARVIS to `amo-arbitrage` production data stores or feeds.
- Changing JARVIS order routing, risk limits, kill switches, PM2, `.env`, active
  instruments, broker credentials, or scheduler behavior.
- Treating commodity/arbitrage screens as validated futures/options alpha in
  `jarvis-trader`.
