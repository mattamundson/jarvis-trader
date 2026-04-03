# RL Reward Tuning Theory — JARVIS Trader

> Reference document for reward function failure modes and tuning decisions.
> Updated after Run 7 results. Covers Runs 6–8 with Run 9 contingencies.

---

## Reward Function Architecture

The `_calculate_reward()` method in `engine/strategies/rl_environment.py` computes per-bar reward as:

```python
reward = pnl_reward        # realized_pnl / atr * pnl_atr_weight
       + hold_cost         # cfg["hold_cost_per_bar"] if position != 0 else 0.0
       + flat_hold_reward  # cfg["flat_hold_reward"] if HOLD action and position == 0
       + entry_cost        # cfg["entry_cost"] if is_new_entry
       + redundant_cost    # cfg["entry_cost"] if BUY-while-long or SELL-while-short
       + t1_bonus          # cfg["t1_bonus"] if realized_pnl/atr >= t1_atr
```

All reward components are dimensionless. `pnl_reward` is normalized by ATR so the reward signal is
scale-invariant across instruments (MES, MNQ, MCL, MGC). The Run 8 config values are:

```python
REWARD_CONFIG = {
    "pnl_atr_weight":    1.0,
    "hold_cost_per_bar": -0.002,   # doubled from Run 7's -0.001
    "entry_cost":        -0.02,    # quartered from Run 7's -0.05 (→ Run 6's -0.10)
    "t1_bonus":           0.10,
    "flat_hold_reward":   0.000,   # removed in Run 7, kept at 0 for Run 8
}
```

---

## 1. Break-Even Analysis

**Definition:** the break-even hold duration is the minimum number of bars a position must remain
open after entry before the accumulated `hold_cost` exactly offsets the `entry_cost`. Below this
threshold, the round-trip entry+hold+exit is guaranteed negative reward before any P&L is considered.

```
break_even_bars = abs(entry_cost) / abs(hold_cost_per_bar)
```

| Run | entry_cost | hold_cost_per_bar | break_even_bars | max_episode_bars | Trades that fit |
|-----|-----------|-------------------|-----------------|-----------------|-----------------|
| 6   | -0.10      | -0.001            | 100             | 500             | ~5              |
| 7   | -0.05      | -0.001            | 50              | 500             | ~10             |
| 8   | -0.02      | -0.002            | **10**          | 500             | **~50**         |

**Key insight:** in Runs 6 and 7, the break-even bar count was so high relative to episode length
that the agent's rational optimum was to enter once, hold the full episode, and collect a single
large P&L. The entry cost was an amortization problem: you only want to amortize a large fixed cost
once, not repeatedly.

Run 8 solves this by attacking both levers simultaneously:
- Halving entry cost makes each entry cheaper (less to amortize).
- Doubling hold cost makes the amortization window shorter and steeper.
- The combined effect is a 10-bar break-even vs. 100 bars in Run 6 — a 10x reduction.

---

## 2. The HOLD-Forever Attractor

### Why the agent converges to n_trades → 0

The HOLD-forever attractor is not irrational behavior — it is the agent finding the global optimum
given the reward landscape. Here is the mechanism:

**Run 6 scenario (break-even = 100 bars):**

In a 500-bar episode, only 5 non-overlapping trades of 100 bars each fit. Each trade must earn a
positive `pnl_reward` large enough to offset its -0.10 entry cost before generating net positive
reward. If the market is noisy (as all real markets are), a meaningful fraction of those 5 trades
will be losers. The agent quickly learns:

- ONE carefully-timed high-quality trade held for 400+ bars: accumulated `hold_cost` = -0.001 × 400 = -0.40, but entry_cost = -0.10, and if the trade pays +2.0 ATR, `pnl_reward` = +2.0 → net reward ≈ +1.50.
- FIVE trades of 80 bars each: entry costs = 5 × -0.10 = -0.50, hold costs = 5 × 80 × -0.001 = -0.40, require total `pnl_reward` > +0.90 just to break even. Any losing trade is catastrophic to the sum.

The ONE-trade strategy dominates in expected value when entry cost is high. The agent discovers
this through PPO's policy gradient updates within ~50k timesteps and locks into it.

**Run 7 scenario (break-even = 50 bars, flat_hold_reward removed):**

Removing `flat_hold_reward = 0.005` eliminated the passive-income stream that had competed with
the HOLD strategy. Naively, this should have pushed the agent toward trading (since HOLDing flat
now yields zero reward). But the agent still returned n_trades = 3 and hold_rate = 98.8%.

Root cause: removing `flat_hold_reward` did not change the fundamental break-even geometry. With
break-even still at 50 bars, the agent needs to hold each trade for 50+ bars just to reach zero
net reward from entry + hold cost before counting P&L. In a 500-bar episode with only 10 such
trades fitting, the ONE-trade attractor remained dominant. The agent did not learn to trade more
— it simply stopped earning passive flat rewards, so episode rewards fell, but the optimal policy
structure did not change.

**Training vs. OOS divergence in Run 7:**

Episode rewards during training were positive (6–8), indicating the agent learned genuinely
profitable per-episode behavior. Yet OOS evaluation over 1,274 bars produced only 3 trades. This
divergence has two causes:

1. **Distribution shift:** Training episodes are random 500-bar windows. The agent's ONE-trade
   strategy was tuned to find the single best setup in each window. In OOS evaluation, the agent
   encounters a contiguous 1,274-bar stretch. It applies the same "wait for the best single setup"
   policy, finds it, holds it, and then idles for the remaining 700+ bars.

2. **No reentry incentive:** With `flat_hold_reward = 0.0` and no hold cost while flat, the
   agent has zero incentive to re-enter after closing the first trade. The reward for flat inaction
   is identical to the reward for a bad trade (both zero), so the agent correctly prefers inaction.

---

## 3. Why Run 8 Should Work

### The two-lever adjustment

Run 8 attacks the attractor from both sides simultaneously:

**Lever 1 — cheap entry (entry_cost = -0.02):**
Entry cost is now small enough that the agent can explore multiple entries during a training
episode without catastrophic reward loss. A wrong-way trade that closes at -0.5 ATR costs:
`pnl_reward = -0.5, entry_cost = -0.02, hold_cost (10 bars) = -0.02` → net = -0.54. That is a
real loss, but not regime-ending. The agent can recover in the next trade.

**Lever 2 — expensive holding (hold_cost_per_bar = -0.002):**
With hold cost doubled, holding a position open for 50 bars now costs -0.10 in pure hold cost
alone. The agent cannot sit on an underwater position and wait for recovery — the hold_cost meter
is running twice as fast. This creates pressure to close losing trades quickly (within ~5–10 bars)
and to take profits before they decay.

### Expected trade frequency arithmetic

With break-even = 10 bars:
- 500 bars / 10 bars per trade cycle = 50 theoretical trade slots per episode.
- At a realistic 60% utilization (agent is selective), expected n_trades = **30–50 per episode**.
- In OOS eval over 1,274 bars: 1,274 / 10 × 0.60 ≈ **75 trades expected** — well above the
  validation gate of min_trades = 60.

### Expected hold rate

`hold_rate` in the validation gates is defined as `min_hold_rate = 0.50`. Run 7 produced a
pathological hold_rate = 98.8% (the agent was in a position almost always — it just never closed
and reopened). Run 8's hold_rate semantics shift:

- The `hold_cost_per_bar` pressure will push average trade duration toward 10–20 bars.
- At 20 bars per trade and 40 trades per 500-bar episode: 800 bars in-position out of 500 available
  → impossible. The constraint resolves to roughly 15–25 bars per trade, ~30 trades per episode,
  and ~450/500 bars in-position = hold_rate ~0.90.

Wait — "hold_rate" here is ambiguous. Looking at `get_episode_metrics()`:

```python
flat_hold_rate = self._hold_when_flat / self._bars_flat if self._bars_flat > 0 else 0.0
```

This is the fraction of **flat bars** during which the agent chose HOLD (vs. BUY/SELL). A
flat_hold_rate of 0.98 means the agent was flat for N bars and issued HOLD on 98% of them. The
validation gate `min_hold_rate = 0.50` requires the agent to hold flat at least half the time —
i.e., not churn constantly. Run 8 should satisfy this naturally because entry_cost = -0.02 still
penalizes random entries while flat.

### Summary of Run 8 expected outcomes

| Metric          | Run 6 actual | Run 7 actual | Run 8 expected |
|-----------------|-------------|-------------|----------------|
| n_trades (OOS)  | 11           | 3            | 30–80          |
| flat_hold_rate  | 0.0          | 0.988        | 0.50–0.75      |
| Episode reward  | ~4–6         | ~6–8         | ~3–8           |
| Profit factor   | unknown      | unknown      | needs eval     |

---

## 4. Remaining Risk Factors

### Risk 1 — Poor signal quality defeats the entry cost reduction

If `realized_pnl / atr` on the average trade is less than `abs(entry_cost + hold_cost_accrued)`,
the agent will still learn to avoid trading because every trade produces a net negative reward.
With entry_cost = -0.02 and hold_cost = -0.002/bar at a 10-bar average hold: each trade must
produce at least `0.02 + 0.002 × 10 = 0.04` ATR in P&L just to break even on costs. That is
0.04 ATR per trade — a very low bar. For MES with ATR ≈ 8 points, that is 0.32 MES points per
trade. The signal quality risk is low at this threshold.

### Risk 2 — T1 bonus relative weight shifts

At entry_cost = -0.10 (Run 6), the T1 bonus of +0.10 was only as large as a single entry cost —
the agent needed multiple T1 hits to meaningfully recover from several entries. At entry_cost =
-0.02 (Run 8), the T1 bonus is **5× the entry cost**. A single T1 hit now dominates the episode
reward signal. This is directionally good (it rewards quality exits), but creates a new failure
mode: the agent may learn to hunt T1 specifically at the cost of overall trade frequency.

Concretely: if the agent discovers that entering at a very selective high-confidence setup (5–10
times per episode) and targeting T1 yields `5 × (T1_reward - entry_cost - hold_cost) = 5 × (0.10 +
pnl_atr - 0.02 - 0.02)` per episode, while 50 mediocre trades yield less cumulative reward, it will
prefer the selective strategy. This could reproduce the low-trade-count attractor through a
different mechanism. Monitor `t1_hit_rate` in OOS metrics.

### Risk 3 — Churn without quality (over-trading)

The inverse failure mode: entry_cost = -0.02 is so low that the agent enters and exits every 2–3
bars (noise churn). This wastes `hold_cost` budget on tiny positions and accumulates entry costs
without meaningful P&L. The symptom is n_trades >> 100 with win_rate < 0.50 and profit_factor <
1.0. The redundant_cost penalty in `_calculate_reward()` guards against BUY-while-long / SELL-while-
short patterns but does not prevent rapid OPEN→CLOSE→OPEN churn via CLOSE+BUY sequences.

If churn appears: raise entry_cost to -0.03 or -0.04 to increase the churn barrier without
returning to the HOLD-forever attractor.

### Risk 4 — Episode reward positive during training but poor OOS (Run 7 pattern)

The same distribution-shift risk exists in Run 8. Training on random 500-bar windows rewards
policies that exploit short-window structure. OOS is a contiguous 1,274-bar stream. If the agent
learns to trade a specific market regime (e.g., trending) that appears in most 500-bar windows
but is less frequent over 6 months, OOS trade count will be lower than training episode averages
suggest. Mitigation: check regime distribution in the training vs. OOS dataset before concluding
the reward config is wrong.

---

## 5. Potential Run 9 Adjustments

Use the decision tree below based on Run 8 OOS results.

### If still under-trading (n_trades < 30)

The HOLD attractor persists. Options:

**Option A — Further reduce entry cost:**
```python
entry_cost = -0.01
hold_cost_per_bar = -0.003
# break_even = 0.01 / 0.003 = 3.3 bars — very aggressive
```
Risk: may produce churn. Use only if Option B fails.

**Option B — Add a mandatory reentry incentive:**
Add a small positive reward for the first BUY/SELL action after being flat for N bars:
```python
# In _calculate_reward():
reentry_bonus = +0.02 if (is_new_entry and self._bars_flat_consecutive > 20) else 0.0
```
This directly penalizes long flat stretches without contaminating the P&L signal.

**Option C — Increase timesteps:**
500k timesteps with break-even = 10 bars may not be enough for PPO to fully explore the entry
landscape. Try 750k timesteps before changing reward config.

### If over-trading / churning (n_trades > 120, profit_factor < 1.2)

The agent is entering without signal quality. Options:

```python
entry_cost = -0.03          # Raise barrier from 0.02
hold_cost_per_bar = -0.002  # Keep same
t1_bonus = 0.15             # Raise T1 incentive to reward quality exits more
# break_even = 0.03 / 0.002 = 15 bars — moderate
```

### If quality fails despite good n_trades (n_trades in range but PF < 2.0)

The issue is signal quality, not reward structure. Options:

1. Increase PPO training: `timesteps = 750_000` — give the policy more gradient updates.
2. Raise entropy coefficient: `ent_coef = 0.07` — forces broader state-space exploration,
   may find better entry conditions in the 18-feature observation space.
3. Review feature quality: check that `stc_value`, `regime_score`, `trend_direction`, and
   `unrealized_pnl_atr` have meaningful variation in the training data (not near-constant).

### Summary table

| Failure mode           | Symptom                        | Primary lever                                 |
|------------------------|--------------------------------|-----------------------------------------------|
| HOLD attractor         | n_trades < 30, hold_rate > 90% | Lower entry_cost → -0.01; raise hold_cost     |
| Churn                  | n_trades > 120, PF < 1.2       | Raise entry_cost → -0.03; raise t1_bonus      |
| Quality failure        | n_trades OK, PF < 2.0          | Raise timesteps; raise ent_coef               |
| OOS distribution shift | Training rewards good, OOS low | Check regime distribution; add reentry bonus  |
| T1 hunting             | n_trades ~10, t1_rate high     | Lower t1_bonus; raise hold_cost slightly      |

---

## 6. Observation Space Notes

The 18-feature state vector (defined in `rl_config.py::STATE_FEATURES`) gives the agent the
following position-awareness signals:

- `current_position` (feature index 15): 1=long, 0=flat, -1=short
- `unrealized_pnl_atr` (feature index 16): unrealized P&L normalized by ATR
- `bars_in_trade_norm` (feature index 17): bars_in_trade / 100

The `bars_in_trade_norm` feature is critical for Run 8 dynamics. As a trade ages, this value
increases, allowing the agent to learn a policy like "close positions after 15–20 bars regardless
of unrealized P&L." Combined with `unrealized_pnl_atr`, the agent has all information needed to
implement a time-stop and profit-target strategy without explicit rule encoding — it can emerge
purely from reward shaping.

The `hold_cost_per_bar = -0.002` in Run 8 creates an implicit gradient in reward space: each
additional bar in a losing position makes the next bar's hold_cost look increasingly bad relative
to closing. The agent should learn to read `unrealized_pnl_atr < -0.5` combined with `bars_in_
trade_norm > 0.10` as a CLOSE signal through repeated negative reward experiences.

---

## Appendix — Run History Summary

| Run | entry_cost | hold_cost | flat_hold_reward | break_even | n_trades | hold_rate | Notes                                |
|-----|-----------|-----------|------------------|------------|----------|-----------|--------------------------------------|
| 1-5 | -0.20→-0.10 | -0.001  | varies           | 200→100    | 14       | high      | No episode windowing; single-trade attractor |
| 6   | -0.10      | -0.001    | +0.005           | 100        | 11       | ~0.0 (flat hold) | Episode windowing added; flat reward created passive income |
| 7   | -0.05      | -0.001    | 0.000            | 50         | 3        | 98.8%     | HOLD attractor persists; training rewards positive but OOS dead |
| 8   | -0.02      | -0.002    | 0.000            | **10**     | TBD      | TBD       | Two-lever fix; expected 30–80 trades |
