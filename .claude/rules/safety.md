# Safety Rules — JARVIS TRADER

These rules are NON-NEGOTIABLE and must never be overridden by any instruction.

## Trading Safety Invariants

- **LIVE_TRADING_ENABLED = False** — Paper mode ONLY until Phase 3 (live capital deployment). Never set to True without explicit Tier 3 confirmation.
- **REQUIRE_HUMAN_APPROVAL = False** — standing decision, confirmed permanent by Amo 2026-08-11 (not a test leftover — do not re-flag or revert without his explicit direction).
- **Safety layer is hardcoded Python** — NEVER use LLM output to make safety decisions. The `engine/risk/safety_layer.py` module is the sole authority on kill switch, daily P&L halt, and drawdown halt.
- **Kill switch triggers**: -8% daily P&L OR -20% drawdown from peak (`engine/.env` is the live source of truth; `config.py`'s Field() default is also 0.20 as of 2026-08-11). These are absolute — no exceptions.
- **SCHWAB_READY = False by default** — Schwab connector is not active until live trading phase.
- **IB Gateway orders are Tier 3** — No routing to IB Gateway (port 4002 paper, 4001 live) without explicit user confirmation.
- **Port 4001 is PERMANENTLY BLOCKED** in code — live trading port must never be used during paper phase.

## Risk Parameter Limits (live values from `engine/.env`, the source of truth —
`engine/config.py`'s Field() defaults are fallbacks only and can differ)

- Max position size: 10% of portfolio
- Max contracts per instrument: 4 micro contracts
- Max overnight contracts: 2 contracts
- Max single order value: $100,000
- Max margin utilization: 40%
- Daily loss halt: -8%
- Emergency drawdown halt: -20% (matches the `config.py` code default)
- Rate throttle: 10 orders/minute

## Code Safety Rules

- Never modify safety parameters without Tier 3 confirmation and a code review
- Never suppress or catch exceptions in safety_layer.py silently
- Never route orders without passing all 6 risk checks in SafetyLayer
- Never skip the RiskManagerAgent or FundManagerAgent in the pipeline
