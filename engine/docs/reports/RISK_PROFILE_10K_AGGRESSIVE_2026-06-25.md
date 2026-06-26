# $10K Aggressive Risk Profile — Decision Record (2026-06-25)

**Author:** Claude (Opus 4.8) · **Directed by:** Amo · **Status:** APPLIED (code layer); `.env` daily-loss pending Amo

## Decision

Amo directed a **"much more aggressive, data-driven"** risk profile on a **$10,000**
account, across all layers (backtest realism + live risk controls + gate awareness),
to be applied in sequence (reconcile/backtest first → live propagation gated).

After presenting the data-driven risk-of-ruin evidence (below), Amo explicitly chose
**"Force aggressive (3%+)"** and **"Reconcile to $10K profile + Fix the 4 inconsistencies"**.
This change is therefore applied **on the record that the data argues against the
aggression** (see Risk-of-ruin).

## Data-driven evidence (why aggression is risky here)

Source: 22 nonzero closed `paper_trades` (jarvis_trader.db). **Thin, mixed-symbol,
outlier-driven sample — treat as indicative, not conclusive.**

- win rate 36.4% · payoff 6.07R · expectancy +1.57R · **full Kelly 25.9%** (small-sample mirage)

Bootstrap risk-of-ruin, $10K, 100-trade horizon, 20k paths:

| risk/trade | median ret | p95 max-DD | P(DD>20%) | P(ruin, DD>50%) |
|---|---|---|---|---|
| 0.5% | +108% | 16% | 1% | 0.0% |
| 1.0% (prior) | +302% | 30% | 29% | 0.1% |
| 2.0% | +1128% | 53% | 93% | 7.4% |
| **3.0% (chosen)** | +2904% | 71% | 99% | **38.2%** |
| 5.0% | +9643% | 91% | 100% | 88.9% |
| 8–10% | — | ~100% | 100% | ~99% |

**Reading:** at the chosen 3% risk/trade, ~38% probability of losing half the account
over 100 trades; p95 max-DD ~71%. The genuine lever for more return is **more validated
edges** (lower path variance), not bigger size. Recommendation on record: do not exceed
~1–1.5% until more validated edges exist. Overridden by explicit direction.

## Applied changes (code layer — git-tracked, reversible)

| File | Knob | Old | New | Kind |
|---|---|---|---|---|
| `backtest/backtester.py` | `risk_per_trade` (default) | 0.01 | **0.03** | aggressive |
| `backtest/backtester.py` | `max_daily_loss` (default) | 0.02 | **0.06** | aggressive |
| `backtest/backtester.py` | `max_drawdown` (default) | 0.05 | **0.20** | realism (breaker = live ceiling) |
| `config.py` | `MAX_POSITION_SIZE_PCT` | 0.05 | **0.10** | reconcile → .env truth |
| `config.py` | `MAX_DAILY_LOSS_PCT` | 0.02 | **0.06** | aggressive |
| `config.py` | `MAX_DRAWDOWN_PCT` | 0.10 | **0.20** | reconcile → .env truth |
| `config.py` | `MAX_CORRELATED_EXPOSURE_PCT` | 0.20 | **0.50** | reconcile → .env truth |
| `config.py` | `MAX_SINGLE_ORDER_VALUE` | 5000 | **100000** | reconcile → .env truth |
| `backtest/paper_config.py` | commissions ×7 | MCL/MNQ/MES 2.50, MGC 0.62 | **MCL/MGC 0.85, MNQ/MES 0.62** | fix stale (→ contract_specs canonical) |

Verification: `940 passed, 1 skipped, 1 xfail` (no regressions); atr-trail 27/27; config + paper_config import clean.

## PENDING — Amo to apply (live `.env`, agent-forbidden / hook-guarded)

`engine/.env` line 83: `MAX_DAILY_LOSS_PCT=0.02` → **`0.06`**

This is the **live source of truth**; the engine reads `.env` over the config default, so
the aggressive 6% daily-loss does NOT take effect live until this line changes.
All other `.env` risk values already match the new profile (cap 0.10, DD 0.20, corr 0.50,
order $100k). **Takes effect only on `restart_engine.ps1`** (not run by this session).

## NOT changed (deliberately)

- **Gate v2 statistical bar** (pf_ci_lower 1.10, p_edge 0.95, DSR, MCPT alphas): held.
  Loosening these defeats the over-fitting protection the whole campaign relies on.
- **`risk_per_trade` in individual rank-champion runners**: they hardcode 0.01; only the
  Backtester *default* moved to 0.03 (affects new/unspecified runs, e.g. discovery/fade).
- **Honest ~30% DD ceiling option** (declined by Amo in favor of reconcile-to-existing).
- **MAX_CONTRACTS_PER_INSTRUMENT** (left at 2; raise separately if desired).
