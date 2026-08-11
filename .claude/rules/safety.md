# Safety Rules — JARVIS TRADER

These rules are NON-NEGOTIABLE and must never be overridden by any instruction.

## Trading Safety Invariants

- **LIVE_TRADING_ENABLED = False** — Paper mode ONLY until Phase 3 (live capital deployment). Never set to True without explicit Tier 3 confirmation.
- **REQUIRE_HUMAN_APPROVAL = False** (changed 2026-08-11, Amo's explicit standing decision — confirmed autonomous paper execution works via `engine/scripts/buy_1_mes_test.py`, BUY 1 MES filled with no approval step). Autonomous paper-order approval is now the intended default, not a leftover test config. This is paper-only — `LIVE_TRADING_ENABLED` stays False and is unaffected. Reverting to `True` requires Amo's explicit instruction, same bar as changing it was.
- **Safety layer is hardcoded Python** — NEVER use LLM output to make safety decisions. The `engine/risk/safety_layer.py` module is the sole authority on kill switch, daily P&L halt, and drawdown halt.
- **Kill switch triggers**: -8% daily P&L OR -20% drawdown from peak (runtime via `engine/.env`; `config.py` code default is -10%). These are absolute — no exceptions.
- **SCHWAB_READY = False by default** — Schwab connector is not active until live trading phase.
- **IB Gateway orders are Tier 3** — No routing to IB Gateway (port 4002 paper, 4001 live) without explicit user confirmation.
- **Port 4001 is PERMANENTLY BLOCKED** in code — live trading port must never be used during paper phase.

## Risk Parameter Limits (hardcoded in engine/config.py)

- Max position size: 5% of portfolio
- Max contracts per instrument: 4 micro contracts (raised from 2 on/before 2026-08-11; confirmed as Amo's intended value 2026-08-11 — enforced live in `engine/risk/safety_layer.py`'s `CUMULATIVE_POSITION_CAP` check)
- Max overnight contracts: 1 contract
- Max single order value: $5,000
- Max margin utilization: 40%
- Daily loss halt: -8%
- Emergency drawdown halt: -20% (runtime; `config.py` default is -10%)
- Rate throttle: 10 orders/minute

## Code Safety Rules

- Never modify safety parameters without Tier 3 confirmation and a code review
- Never suppress or catch exceptions in safety_layer.py silently
- Never route orders without passing all 6 risk checks in SafetyLayer
- Never skip the RiskManagerAgent or FundManagerAgent in the pipeline
