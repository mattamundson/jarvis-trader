# Volatility Regime Testing Strategy

## Goal

Make the SPY/QQQ/VIX volatility-regime layer testable before any options payoff model or paper execution depends on it.

## Test layers

### Layer 1 — Pure unit tests, fast

Purpose: catch math and classification bugs.

Required coverage:

- date normalization from `timestamp` and `date` columns;
- duplicate/misordered dates;
- log returns and forward returns;
- realized-vol columns;
- VIX/VIX3M term-state boundaries;
- IV/RV premium-state boundaries;
- regime classifier precedence;
- missing VIX / missing VIX3M behavior.

Runtime target: <2 seconds.

### Layer 2 — Fixture integration tests, fast-medium

Purpose: run the full module on deterministic mini CSV-style fixtures.

Required coverage:

- SPY/QQQ-like daily cache;
- VIX and VIX3M aligned daily cache;
- partial VIX alignment;
- expected output columns and regime counts;
- latest snapshot JSON-safe fields.

Runtime target: <5 seconds.

### Layer 3 — CLI artifact tests, fast-medium

Purpose: ensure the research script produces durable artifacts.

Required coverage:

- temp cache dir with synthetic SPY/QQQ/VIX/VIX3M CSVs;
- `vol_regime_study.run()` writes JSON + frame CSV + summary CSV;
- data gaps are explicit when VIX/VIX3M absent;
- output spans/row counts are correct.

Runtime target: <10 seconds.

### Layer 4 — Historical research validation, slower

Purpose: validate whether regimes separate future distributions.

Required coverage:

- full local SPY/QQQ daily caches;
- VIX/VIX3M history when present or fetched;
- forward 1d/3d/5d returns by regime;
- forward realized-vol expansion/contraction by regime;
- out-of-sample split by decade / pre-COVID / post-COVID / high-rate era;
- bootstrap confidence intervals for regime means/win rates.

Runtime target: seconds to minutes.

### Layer 5 — Payoff model tests, fast-medium

Purpose: validate option structure math before strategy research.

Required coverage:

- debit spread max loss / max profit / breakeven;
- credit spread max loss / max profit / breakeven;
- iron condor max loss / max profit / breakevens;
- calendar spread sanity checks;
- VIX spread payoff behavior;
- bid/ask/slippage assumptions.

### Layer 6 — Real-chain replay / certification, slow

Purpose: certify strategy candidates on real bid/ask/IV/Greeks snapshots.

Required coverage:

- stored chain snapshots;
- liquidity/spread filters;
- fill assumptions;
- daily mark and exit lifecycle;
- WFO + Monte Carlo + DSR;
- gate-v2-equivalent certification.

## Rule

A green Layer 1/2/3 test suite means the **code path is correct enough to research**.
It does not mean the **strategy has edge**. Edge claims require Layer 4+ and certification requires Layer 6.
