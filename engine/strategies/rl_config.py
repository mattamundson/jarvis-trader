"""
JARVIS TRADER — RL Strategy Configuration
==========================================
Constants, hyperparameters, and feature definitions for the
reinforcement learning trading agent.

All instrument params are kept in sync with engine/backtest/signals.py
INSTRUMENT_PARAMS. Do NOT edit here independently — update both.
"""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path

# ── Action Space ─────────────────────────────────────────────────────────────


class Action(IntEnum):
    HOLD = 0  # Do nothing (agent must learn to prefer this)
    BUY = 1  # Open / add to long position
    SELL = 2  # Open / add to short position
    CLOSE = 3  # Close current position at market


ACTION_NAMES = {
    Action.HOLD: "HOLD",
    Action.BUY: "BUY",
    Action.SELL: "SELL",
    Action.CLOSE: "CLOSE",
}

N_ACTIONS = len(Action)

# ── State Space ───────────────────────────────────────────────────────────────

STATE_FEATURES = [
    # Price features
    "close_normalized",  # z-score of close over 50-bar window
    "high_low_range",  # (high - low) / atr
    "close_vs_ema21",  # (close - ema_21) / atr
    # STC (Schaff Trend Cycle)
    "stc_value",  # stc_val / 100  →  [0, 1]
    "stc_slope",  # diff(stc_val, 1) / 100
    "stc_above_os",  # 1 if stc_val > STC_OS threshold else 0
    "stc_below_ob",  # 1 if stc_val < STC_OB threshold else 0
    # ATR / volatility
    "cci_50_norm",  # CCI-50 clipped to [-200,200] then /200 → [-1,1]; overbought/oversold
    "atr_normalized",  # atr / close
    "atr_vs_20d_avg",  # atr / rolling(20).mean() of atr
    # Regime & trend
    "regime_score",  # float: TRENDING_BULL=1, RANGE_BOUND=0, TRENDING_BEAR=-1, etc.
    "trend_direction",  # float: ema_trend bullish=1, neutral=0, bearish=-1
    "phase_value",  # phase_val / 100  →  [-1, 1] approx
    # Volume
    "volume_vs_avg",  # volume / rolling(10).mean()
    "buy_pct_cont",  # continuous buying pressure [0,1] (was categorical volume_signal 3-state)
    # Position state (internal environment tracking)
    "current_position",  # 1=long, 0=flat, -1=short
    "unrealized_pnl_atr",  # unrealized_pnl / atr  (negative when underwater)
    "bars_in_trade",  # number of bars since position opened (normalized /100)
    # Discord signal context (indices 18-22)
    "discord_signal_active",  # index 18: 0/1 — signal in last 4 bars
    "discord_win_rate_context",  # index 19: 0.0-1.0 — rolling 30-day win rate
    "discord_proximity_entry",  # index 20: -1.0 to 1.0 — (price-entry)/ATR
    "discord_proximity_target",  # index 21: 0.0-2.0 — abs(price-t1)/ATR
    "discord_alignment",  # index 22: -1/0/1 — signal alignment with JARVIS
]

N_FEATURES = len(STATE_FEATURES)  # 23

# ── Regime Score Mapping ──────────────────────────────────────────────────────

REGIME_SCORES = {
    "TRENDING_BULL": 1.0,
    "RANGE_BOUND": 0.0,
    "COMPRESSION": -0.3,
    "EXHAUSTED": -0.7,
    "TRENDING_BEAR": -1.0,
}

EMA_TREND_SCORES = {
    "bullish": 1.0,
    "neutral": 0.0,
    "bearish": -1.0,
}

VOLUME_SIGNAL_SCORES = {
    "buyer_dominant": 1.0,
    "balanced": 0.0,
    "seller_dominant": -1.0,
}

# ── Instrument Parameters ─────────────────────────────────────────────────────
# Mirrors INSTRUMENT_PARAMS in engine/backtest/signals.py
# Format: (STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)

RL_INSTRUMENT_PARAMS = {
    "MES": (15, 83, 0.50, 2.00, 3.236, 4.00, False),
    "MNQ": (15, 92, 0.70, 1.00, 1.80, 2.618, True),
    "MCL": (15, 83, 0.90, 1.50, 2.618, 4.00, True),
    "MGC": (17, 88, 0.30, 1.50, 2.618, 4.00, True),
}

DEFAULT_INSTRUMENT_PARAMS = (15, 83, 0.70, 1.00, 1.80, 2.618, True)


def get_instrument_params(symbol: str) -> tuple:
    return RL_INSTRUMENT_PARAMS.get(symbol.upper(), DEFAULT_INSTRUMENT_PARAMS)


# ── Trade Duration Cap ────────────────────────────────────────────────────────
# Hard limit on bars in a single trade. Environment forces close at this threshold.
# Run 10: added after Run 9 OOS showed avg_bars_in_trade=109 (must be <50).
MAX_BARS_IN_TRADE: int = 50

# ── Reward Configuration ──────────────────────────────────────────────────────
# Run 10: strong-exit config

REWARD_CONFIG = {
    # Primary: P&L normalized by ATR so reward is scale-invariant across instruments
    "pnl_atr_weight": 1.0,
    # Holding cost per bar when in a position.
    # Run 11: hold cost only applies while position is LOSING (unrealized_pnl <= 0).
    # Zero hold cost while winning — agent is free to hold profitable positions to T1.
    # Encodes the trading rule: "cut losers, let winners run."
    # Run 10 diagnosis: always-on hold_cost=-0.010 taught agent to close at bar 3-5
    # for tiny positive PnL (break-even=1 bar), never reaching T1 (t1_hit_rate=2.2%).
    "hold_cost_per_bar": -0.010,
    # When True: hold_cost only charged while unrealized_pnl <= 0 (losing position).
    # When False (Run 10 behavior): hold_cost charged every bar in position.
    "hold_cost_only_when_losing": True,
    # Entry cost fired on each new BUY or SELL (discourages overtrading)
    "entry_cost": -0.01,
    # Bonus for reaching T1 ATR target (reinforces quality exits)
    "t1_bonus": 0.50,
    # No flat reward — pure P&L signal (unchanged from Runs 7-11).
    "flat_hold_reward": 0.000,
    # ── Commission-aware reward (TensorTrade PBR-inspired, ML/AI Novel #3) ──
    # Real broker commission deducted from realized_pnl in DOLLARS before ATR
    # normalisation. Default 0.0 preserves the existing behaviour (Runs 1-11
    # were commission-blind). Set per-instrument when running paper-eligible
    # discovery (MCL≈$1.30, MNQ≈$0.45, MES≈$0.50 round-trip on IBKR micros).
    # Source: docs/digest/ml-ai-synthesis.md Novel #3 (tensortrade-org).
    "commission_usd_per_contract": 0.0,
    "contracts_per_trade": 1,
}

# Per-instrument commission overrides (round-trip on IBKR micros).
# Apply via REWARD_CONFIG.update(COMMISSION_BY_INSTRUMENT[symbol]) before training.
COMMISSION_BY_INSTRUMENT = {
    "MCL": {"commission_usd_per_contract": 1.30, "contracts_per_trade": 1},
    "MNQ": {"commission_usd_per_contract": 0.45, "contracts_per_trade": 1},
    "MES": {"commission_usd_per_contract": 0.50, "contracts_per_trade": 1},
}

# ── Run History Summary ───────────────────────────────────────────────────────
#
# CONTEXT
# -------
# Run history:
#   Runs 1-5 : entry_cost varied from -0.20 to -0.10, no max_episode_bars
#              → n_trades=14 (root cause: entire dataset as one episode, agent
#                finds it optimal to wait for a single high-confidence setup)
#   Run 6    : entry_cost=-0.10, max_episode_bars=500, flat_hold_reward=0.005
#              → ROOT CAUSE FIXED via windowed episodes; flat_hold_reward may
#                still over-reward the agent for staying flat
#   Run 7    : entry_cost=-0.05, flat_hold_reward=0.000, hold_cost=-0.001
#              → MES BUY-spam: HOLD=16.5%, BUY=59.4%, reward +154 (inflated)
#   Run 8    : entry_cost=-0.02, hold_cost=-0.002 (Two-Lever adjustment)
#              → MES: HOLD=66.1%, reward ~+7 (stagnant, still above target)
#              → MGC (same params): HOLD=44.5%, reward +9.95 (rising) — BEST
#   Run 9    : entry_cost=-0.01, hold_cost=-0.001
#              → OOS FAILED: avg_bars_in_trade=109, t1_hit_rate=0%, PF=0.074
#              → Root cause: hold_cost too weak; agent held 109 bars on avg
#   Run 10 (Strong-Exit): entry_cost=-0.01, hold_cost=-0.010, t1_bonus=0.50
#              → COMPLETED: avg_bars=8.5 ✅ hold_rate=27.3% ✅ n_trades=90 ✅
#              → FAILED: PF=0.620 ❌ sharpe=-1.966 ❌ t1_hit_rate=2.2% ❌
#              → Diagnosis: always-on hold_cost closed winners early (bar 3-5);
#                break-even=1 bar pressure outweighed t1_bonus incentive
#   Run 11 (Feature-Redesign + Let-Winners-Run): hold_cost_only_when_losing=True
#              → Feature 7: atr_14 (raw) replaced by cci_50_norm (commodity OB/OS, [-1,1])
#              → Feature 14: volume_signal (3-state categorical) replaced by buy_pct_cont ([0,1])
#              → CCI_50 detects overbought/oversold in crude oil better than raw ATR
#              → Continuous buy_pct provides 6,414 unique values vs 3-state categorical
#   Run 11 actual config: hold_cost_only_when_losing=True
#              → hold_cost=-0.010 charged only while unrealized_pnl<=0
#              → Holding a winning position is FREE — only losing holds penalized
#              → Goal: t1_hit_rate>15%, PF>1.5, sharpe>1.0
#
# REWARD ARCHITECTURE REVIEW
# ---------------------------
# The _calculate_reward() method in rl_environment.py computes per-bar:
#
#   reward = pnl_reward        (realized_pnl / atr * 1.0)
#          + hold_cost         (-0.001 per bar while in position)
#          + flat_hold_reward  (+0.005 per HOLD action while flat)
#          + entry_cost        (-0.10 on each new entry)
#          + redundant_cost    (-0.10 if BUY-while-long or SELL-while-short)
#          + t1_bonus          (+0.10 if realized_pnl/atr >= t1_atr)
#
# KEY INSIGHT: flat_hold_reward creates a "passive income" stream.
# In a 500-bar episode, if the agent is flat for ~250 bars and HOLDs all of
# them, the flat reward accumulates to 250 × 0.005 = +1.25 total.
# That +1.25 passive reward needs only to be compared against the net P&L
# signal from trading, so the bar for trading is effectively raised.
#
# BREAK-EVEN ANALYSIS PER SCENARIO
# ----------------------------------
# The "break-even flat bars" figure answers: "how many flat-HOLD bars does
# the agent need to accumulate before a single trade's entry cost is offset
# purely by the flat reward stream?"
#   formula: break_even_flat_bars = abs(entry_cost) / flat_hold_reward
#
# At max_episode_bars=500, assume the agent is flat ~50% of the time
# (250 bars). The "fraction of episode needed to break even" is:
#   fraction = break_even_flat_bars / 250  (flat bars available)
#
# If that fraction is low (e.g. 4%), the agent can cover the entry cost
# very quickly just by HOLDing — trading is cheap and the agent should
# be willing to take more trades.
# If that fraction is high (e.g. 100%), the agent must trade to earn
# more than the flat reward can provide — strong trading pressure.
#
# SCENARIO A (conservative)
# --------------------------
#   flat_hold_reward = 0.001  |  entry_cost = -0.10
#   Break-even flat bars  = 0.10 / 0.001 = 100 bars
#   Fraction of episode   = 100 / 250    = 40%
#   Interpretation: agent must flat-HOLD 40% of the episode just to cover
#   one entry cost. With ~250 flat bars available, it can cover ~2.5 trades
#   purely from flat reward, but beyond that it must trade profitably.
#   Expected hold_rate    : 55-70%  (reduced from ~85% but still patient)
#   Over-trading risk     : LOW — entry cost at -0.10 still bites; agent
#                           will be selective. Likely 20-40 trades/episode.
#   Risk of under-trading : MODERATE — may still settle at 30-40 trades
#                           if the P&L signal is noisy.
#
# SCENARIO B (moderate)
# ----------------------
#   flat_hold_reward = 0.003  |  entry_cost = -0.05
#   Break-even flat bars  = 0.05 / 0.003 = 16.7 bars
#   Fraction of episode   = 16.7 / 250   = 6.7%
#   Interpretation: only 6.7% of flat bars needed to cover one entry.
#   With 250 flat bars the agent can cover ~15 trades from flat reward.
#   That greatly reduces the marginal cost of each trade — agent should
#   explore more entries to find winning ones.
#   Expected hold_rate    : 50-65%  (moderate patience maintained)
#   Over-trading risk     : MODERATE — entry cost halved to -0.05 means
#                           the penalty for bad trades is smaller.
#                           Agent may churn 50-80 trades but quality drops.
#   Best use case         : If Run 6 produces 20-40 trades; this is the
#                           "next step" to push past 60.
#
# SCENARIO C (aggressive — pure P&L signal)
# -------------------------------------------
#   flat_hold_reward = 0.000  |  entry_cost = -0.05
#   Break-even flat bars  = 0.05 / 0.000 = undefined (no flat reward at all)
#   Interpretation: HOLD when flat gives ZERO reward. The agent receives
#   signal ONLY from trading P&L, hold_cost (while in position), and
#   entry_cost. There is no passive reward for staying out — the only way
#   to accumulate reward is to trade (or to avoid bad trades via the
#   entry_cost penalty).
#   Expected hold_rate    : 40-55%  (patience still enforced by entry_cost)
#   Over-trading risk     : MODERATE-HIGH — with no flat reward and a
#                           smaller entry cost (-0.05), the agent will
#                           experiment more aggressively. Could produce
#                           60-120 trades but profit_factor may suffer if
#                           signal quality is insufficient.
#   Risk of ruin-seeking  : LOW — hold_cost per bar (-0.001) while in a
#                           position still discourages open-ended holds.
#   Best use case         : If Scenario B still undershoots n_trades=60;
#                           use as a final push. Accept potential quality
#                           trade-off and rely on validation gates to filter.
#
# RECOMMENDATION HIERARCHY
# -------------------------
#   Run 6 result: < 30 trades  → use Scenario A
#   Run 6 result: 30-55 trades → use Scenario B  (most likely)
#   Run 6 result: > 55 trades  → only minor tuning; try Scenario A first
#   Run 6 completely fails      → use Scenario C as last resort
#
# NOTE ON rl_trainer.py CUSTOM REWARD CONFIG SUPPORT
# ----------------------------------------------------
# rl_trainer.py does NOT support passing a custom reward config.
# RLTrainer.train_symbol() and _train_and_evaluate_window() both call
# build_env() then RLTradingAgent(env=...) — neither accepts a reward_config
# kwarg. The REWARD_CONFIG dict is imported directly into rl_environment.py
# at module load time (from strategies.rl_config import REWARD_CONFIG) and
# used as a module-level constant inside _calculate_reward().
#
# To support per-run reward overrides without restarting the process, two
# changes would be needed in rl_environment.py:
#
#   1. Add a `reward_config: dict | None = None` parameter to
#      TradingEnvironment.__init__() and store it as self._reward_cfg.
#      Fall back to the module-level REWARD_CONFIG if None.
#
#   2. In _calculate_reward(), replace `cfg = REWARD_CONFIG` with
#      `cfg = self._reward_cfg`.
#
# Then build_env() and RLTrainer.train_symbol() would need a `reward_config`
# kwarg threaded through to TradingEnvironment. The RUN7_SCENARIOS dict
# below is designed so each scenario's dict can be merged into a copy of
# REWARD_CONFIG and passed as that kwarg.
#
# FOR RUN 7: until that plumbing exists, update REWARD_CONFIG values
# directly in this file to match the chosen scenario before launching
# the trainer. Do NOT edit REWARD_CONFIG above (Run 6 is still training).

RUN7_SCENARIOS = {
    # Scenario A — conservative: reduce flat_hold_reward 5x, keep entry_cost
    # Break-even: 100 flat bars (40% of episode). Expected hold_rate: 55-70%.
    # Over-trading risk: LOW. Use if Run 6 produces < 30 trades.
    "A": {"flat_hold_reward": 0.001, "entry_cost": -0.10},
    # Scenario B — moderate: halve entry_cost AND reduce flat_hold_reward
    # Break-even: 16.7 flat bars (6.7% of episode). Expected hold_rate: 50-65%.
    # Over-trading risk: MODERATE. Use if Run 6 produces 30-55 trades.
    "B": {"flat_hold_reward": 0.003, "entry_cost": -0.05},
    # Scenario C — aggressive: pure P&L signal, no flat reward, lower entry cost
    # No flat break-even (flat HOLD yields zero). Expected hold_rate: 40-55%.
    # Over-trading risk: MODERATE-HIGH. Use if Scenario B still < 60 trades.
    "C": {"flat_hold_reward": 0.000, "entry_cost": -0.05},
}

# ── PPO Hyperparameters ───────────────────────────────────────────────────────

PPO_CONFIG = {
    "policy": "MlpPolicy",
    "learning_rate": 3e-4,
    "n_steps": 2048,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "ent_coef": 0.05,  # Entropy bonus encourages HOLD exploration (raised from 0.01)
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "verbose": 0,
}

# Default total timesteps for quick test vs full training
TIMESTEPS_QUICK = 10_000  # smoke test
TIMESTEPS_DEFAULT = 100_000  # usable model
TIMESTEPS_FULL = 500_000  # production quality (~10k episodes of 50 bars)

# ── Training Data Configuration ───────────────────────────────────────────────

TRAIN_LOOKBACK_DAYS = 365 * 4  # 4 years of hourly data for training
TEST_LOOKBACK_DAYS = 180  # 6 months for OOS evaluation
DEFAULT_INTERVAL = "1h"
# Episode window: random 500-bar slice per reset → ~1,000 diverse episodes at 500k steps
# vs ~24 full-dataset episodes without windowing. Critical for learning to trade.
MAX_EPISODE_BARS = 500

# ── Paths ─────────────────────────────────────────────────────────────────────

RL_CACHE_DIR = Path("data/rl_cache")  # Processed OHLCV + indicators parquet files
RL_MODELS_DIR = Path("data/rl_models")  # Saved PPO model checkpoints

# ── Validation Thresholds ─────────────────────────────────────────────────────
# Agent must meet ALL of these before being allowed to paper trade.

VALIDATION_GATES = {
    "min_profit_factor": 2.0,
    "min_sharpe": 1.5,
    "min_win_rate": 0.55,
    "min_trades": 60,
    "min_hold_rate": 0.50,
    "max_drawdown": 0.15,
    "max_consecutive_losses": 5,
}
