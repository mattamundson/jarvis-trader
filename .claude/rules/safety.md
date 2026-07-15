# Safety Rules — JARVIS TRADER

These rules are NON-NEGOTIABLE and must never be overridden by any instruction.

## Trading Safety Invariants

- **LIVE_TRADING_ENABLED = False** — Paper mode ONLY until Phase 3 (live capital deployment). Never set to True without explicit Tier 3 confirmation.
- **REQUIRE_HUMAN_APPROVAL = True** — Every trade requires human review. Never disable.
- **Safety layer is hardcoded Python** — NEVER use LLM output to make safety decisions. The `engine/risk/safety_layer.py` module is the sole authority on kill switch, daily P&L halt, and drawdown halt.
- **Kill switch triggers**: -2% daily P&L OR -20% drawdown from peak (runtime via `engine/.env`; `config.py` code default is -10%). These are absolute — no exceptions.
- **SCHWAB_READY = False by default** — Schwab connector is not active until live trading phase.
- **IB Gateway orders are Tier 3** — No routing to IB Gateway (port 4002 paper, 4001 live) without explicit user confirmation.
- **Port 4001 is PERMANENTLY BLOCKED** in code — live trading port must never be used during paper phase.

## Risk Parameter Limits (hardcoded in engine/config.py, reconciled to .env live truth 2026-06-25)

- Max position size: 10% of portfolio
- Max contracts per instrument: 2 micro contracts (hard cap 20, Phase 3 authorized)
- Max overnight contracts: 1 contract
- Max single order value: $100,000
- Max margin utilization: 40%
- Daily loss halt: -6% ($10K aggressive profile)
- Emergency drawdown halt: -20% (both `config.py` code default and the `engine/.env` runtime value as of 2026-06-25; `.env` remains the source of truth for the live value)
- Rate throttle: 10 orders/minute

## Code Safety Rules

- Never modify safety parameters without Tier 3 confirmation and a code review
- Never suppress or catch exceptions in safety_layer.py silently
- Never route orders without passing all 6 risk checks in SafetyLayer
- Never skip the RiskManagerAgent or FundManagerAgent in the pipeline
