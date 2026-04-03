# Strategy canon

Authoritative references for the STC + ATR + regime stack and validation math:

| Doc | Purpose |
|-----|---------|
| [TRADING_RULES.md](TRADING_RULES.md) | Human-readable rules, gates, and instrument policy |
| [EQUATIONS.md](EQUATIONS.md) | Formulas and indicator definitions |
| [STRATEGY_CANON_REVIEW.html](STRATEGY_CANON_REVIEW.html) | Generated review artifact (open in browser) |

Code parameters for backtests and signals live in `engine/backtest/signals.py` (`INSTRUMENT_PARAMS`, STC bands, ATR multipliers). Tier-3 change control applies per project rules.
