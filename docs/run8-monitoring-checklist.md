# Run 8 Monitoring Checklist

**Config**: entry_cost=-0.02, hold_cost=-0.002, T1_bonus=+0.10 (5x entry cost)
**Prior**: Run 6 → n_trades=11, Run 7 → n_trades=3 (HOLD-attractor). Target: trades ≥ 60.

---

## Primary Gates (all must pass)

| Metric | Target | Status |
|--------|--------|--------|
| profit_factor | ≥ 2.0 | |
| sharpe | ≥ 1.5 | |
| win_rate | ≥ 0.55 | |
| n_trades | ≥ 60 | |
| hold_rate | 0.50 – 0.85 | |
| max_drawdown | ≤ 0.15 | |

---

## Run 8 Specific Metrics

| Metric | Healthy Range | Red Flag |
|--------|--------------|----------|
| t1_hit_rate | < 0.80 | ≥ 0.80 = T1-hunting |
| avg_bars_in_trade | 10 – 30 | < 5 = churning, > 100 = over-holding |
| flat_hold_rate | 0.40 – 0.70 | < 0.20 = entering too aggressively |

**T1-hunting**: Agent scores 5x entry cost on T1 exits — if t1_hit_rate ≥ 0.80, it's cherry-picking easy exits and ignoring valid setups.

---

## Diagnosis Table

| n_trades | hold_rate | Diagnosis | Next Action |
|----------|-----------|-----------|-------------|
| < 30 | > 85% | HOLD-attractor persists | entry_cost=-0.01, hold_cost=-0.003 |
| 30–59 | 70–85% | Improving, not enough | entry_cost=-0.01, hold_cost=-0.002 |
| 60+ | 50–85% | **TARGET RANGE** | Proceed to walk-forward |
| 60+ | < 50% | Over-trading | entry_cost=-0.04, hold_cost=-0.001 |
| > 120 | < 40% | Churning | entry_cost=-0.05, t1_bonus=0.15 |

---

## Quality Fixes (after n_trades gate passes)

- **PF < 2.0, trades ≥ 60**: increase timesteps to 750k, ent_coef=0.07
- **Sharpe < 1.5, PF ≥ 2.0**: likely outlier trade — re-run same config
- **Drawdown > 0.15**: tighten stop_loss via `stop_atr` in `rl_config.py`

---

## Quick Commands

```bash
# Train Run 8
curl -X POST http://localhost:8010/strategies/rl/train \
  -H "X-API-Key: [REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MES","timesteps":500000}'

# Monitor
python /tmp/eval_run7.py

# Walk-forward (gates passed)
curl -X POST http://localhost:8010/strategies/rl/train-walkforward \
  -H "X-API-Key: [REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MES","timesteps":500000,"n_windows":8}'
```
