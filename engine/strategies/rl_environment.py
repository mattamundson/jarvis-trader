"""
JARVIS TRADER — RL Trading Environment
========================================
Gymnasium-compatible trading environment that uses jarvis-trader's
existing signal pipeline as the observation space.

State  : 23 float features — 18 from signals.py compute_all_indicators()
         + 5 Discord signal context features (indices 18-22)
Actions: HOLD=0, BUY=1, SELL=2, CLOSE=3  (Discrete 4)
Reward : P&L / ATR  −  hold cost  −  entry cost

Usage:
    from strategies.rl_environment import TradingEnvironment, build_env

    env = build_env("MES", df)   # df = processed DataFrame from signals.py
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(Action.BUY)

    # With Discord signal context (optional — backward compatible):
    from engine.discord.signal_context import DiscordSignalContext
    ctx = DiscordSignalContext()
    env = build_env("MES", df, discord_context=ctx)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import gymnasium as gym
    from gymnasium import spaces

    GYM_AVAILABLE = True
    _GymBase = gym.Env
except ImportError:
    GYM_AVAILABLE = False
    gym = None  # type: ignore
    _GymBase = object  # type: ignore

from backtest.signals import compute_all_indicators, layer1_regime
from discord.signal_context import DiscordSignalContext
from strategies.rl_config import (
    EMA_TREND_SCORES,
    MAX_BARS_IN_TRADE,
    MAX_EPISODE_BARS,
    N_ACTIONS,
    N_FEATURES,
    REGIME_SCORES,
    REWARD_CONFIG,
    Action,
    get_instrument_params,
)

logger = logging.getLogger(__name__)


# ── Feature Extraction ────────────────────────────────────────────────────────


def extract_features(
    df: pd.DataFrame,
    idx: int,
    position: int,
    entry_price: float,
    bars_in_trade: int,
    symbol: str,
) -> np.ndarray:
    """
    Extract the 18-feature base state vector from a single DataFrame row.

    Discord signal context features (indices 18-22) are appended separately
    in TradingEnvironment._get_obs() when a discord_context is provided.

    Parameters
    ----------
    df        : DataFrame with all indicators computed via compute_all_indicators()
    idx       : Current bar index (integer location)
    position  : Current position: 1=long, 0=flat, -1=short
    entry_price: Price at which current position was opened (0.0 if flat)
    bars_in_trade: Number of bars since position opened
    symbol    : Instrument symbol (for STC thresholds)

    Returns
    -------
    np.ndarray of shape (18,), dtype float32 — base features only
    """
    row = df.iloc[idx]
    stc_os, stc_ob = get_instrument_params(symbol)[:2]
    atr = float(row.get("atr", 1.0) or 1.0)
    close = float(row.get("close", 0.0))

    # ── Price features ──────────────────────────────────────────────────────
    # z-score close over trailing 50-bar window
    window_start = max(0, idx - 49)
    close_window = df["close"].iloc[window_start : idx + 1]
    mu = close_window.mean()
    sigma = close_window.std() or 1.0
    close_normalized = float((close - mu) / sigma)

    high = float(row.get("high", close))
    low = float(row.get("low", close))
    high_low_range = float((high - low) / atr) if atr > 0 else 0.0

    ema21 = float(row.get("ema_21", close) or close)
    close_vs_ema21 = float((close - ema21) / atr) if atr > 0 else 0.0

    # ── STC ─────────────────────────────────────────────────────────────────
    stc_raw = float(row.get("stc_val", 50.0) or 50.0)
    stc_value = stc_raw / 100.0

    # Slope: current - previous bar's stc_val
    if idx > 0:
        prev_stc = float(df["stc_val"].iloc[idx - 1] or 50.0)
    else:
        prev_stc = 50.0
    stc_slope = (stc_raw - prev_stc) / 100.0

    stc_above_os = 1.0 if stc_raw > stc_os else 0.0
    stc_below_ob = 1.0 if stc_raw < stc_ob else 0.0

    # ── ATR / volatility ────────────────────────────────────────────────────
    # atr_14 replaced by cci_50_norm: commodity-specific overbought/oversold signal.
    # Raw ATR is scale-dependent (MCL ~1.5, MES ~20) and redundant with atr_normalized.
    # CCI > 100 = overbought, CCI < -100 = oversold; clip to [-200, 200] → divide by 200.
    cci_raw = float(row.get("cci_50", 0.0) or 0.0)
    cci_50_norm = float(max(-1.0, min(1.0, cci_raw / 200.0)))
    atr_normalized = float(atr / close) if close > 0 else 0.0

    window_start_atr = max(0, idx - 19)
    atr_window = df["atr"].iloc[window_start_atr : idx + 1].dropna()
    atr_avg_20 = float(atr_window.mean()) if len(atr_window) > 0 else atr
    atr_vs_20d_avg = float(atr / atr_avg_20) if atr_avg_20 > 0 else 1.0

    # ── Regime & trend ──────────────────────────────────────────────────────
    regime_str = layer1_regime(row)
    regime_score = REGIME_SCORES.get(regime_str, 0.0)

    ema_trend_str = str(row.get("ema_trend", "neutral") or "neutral")
    trend_direction = EMA_TREND_SCORES.get(ema_trend_str, 0.0)

    phase_raw = float(row.get("phase_val", 0.0) or 0.0)
    phase_value = phase_raw / 100.0

    # ── Volume ──────────────────────────────────────────────────────────────
    volume = float(row.get("volume", 0.0) or 0.0)
    vol_window = df["volume"].iloc[max(0, idx - 9) : idx + 1].dropna()
    vol_avg = float(vol_window.mean()) if len(vol_window) > 0 else 1.0
    volume_vs_avg = float(volume / vol_avg) if vol_avg > 0 else 1.0

    # buy_pct_cont replaces categorical volume_signal: continuous [0, 1] buying pressure.
    # 0.0 = all sellers, 0.5 = balanced, 1.0 = all buyers. Higher resolution than 3-state.
    buy_pct_raw = float(row.get("buy_pct", 50.0) or 50.0)
    volume_signal = float(buy_pct_raw / 100.0)  # normalize [0, 100] → [0, 1]

    # ── Position state ───────────────────────────────────────────────────────
    current_position = float(position)

    unrealized_pnl = 0.0
    if position != 0 and entry_price > 0:
        unrealized_pnl = (close - entry_price) * position
    unrealized_pnl_atr = float(unrealized_pnl / atr) if atr > 0 else 0.0

    bars_in_trade_norm = float(bars_in_trade) / 100.0

    obs = np.array(
        [
            close_normalized,
            high_low_range,
            close_vs_ema21,
            stc_value,
            stc_slope,
            stc_above_os,
            stc_below_ob,
            cci_50_norm,  # was: atr_14 (raw, scale-dependent) → CCI normalized [-1,1]
            atr_normalized,
            atr_vs_20d_avg,
            regime_score,
            trend_direction,
            phase_value,
            volume_vs_avg,
            volume_signal,
            current_position,
            unrealized_pnl_atr,
            bars_in_trade_norm,
        ],
        dtype=np.float32,
    )

    # Replace any NaN/inf with 0.0
    obs = np.nan_to_num(obs, nan=0.0, posinf=2.0, neginf=-2.0)
    return obs


# ── Environment ───────────────────────────────────────────────────────────────


class TradingEnvironment(_GymBase):
    """
    Gymnasium-compatible trading environment for jarvis-trader.

    Parameters
    ----------
    symbol          : Futures symbol (MES, MNQ, MCL)
    df              : DataFrame with OHLCV + all indicators from compute_all_indicators()
    initial_capital : Starting capital for P&L tracking
    max_position    : Maximum position size in contracts (default 1)
    discord_context : Optional DiscordSignalContext instance. When provided, appends
                      5 Discord signal features (indices 18-22) to each observation.
                      When None (default), those indices are filled with zeros for
                      full backward compatibility.

    Observation space : Box(shape=(23,), dtype=float32)  — 18 base + 5 discord
    Action space      : Discrete(4) — HOLD, BUY, SELL, CLOSE
    """

    def __init__(
        self,
        symbol: str,
        df: pd.DataFrame,
        initial_capital: float = 10_000.0,
        max_position: int = 1,
        max_episode_bars: int = MAX_EPISODE_BARS,
        reward_config: dict | None = None,
        discord_context: Optional[DiscordSignalContext] = None,
    ):
        if not GYM_AVAILABLE:
            raise ImportError("gymnasium is required: pip install gymnasium")

        self.symbol = symbol.upper()
        self.df = df.reset_index(drop=True)
        self.initial_capital = initial_capital
        self.max_position = max_position
        self.n_bars = len(df)
        # Episode window length — random start per episode gives diverse training experience.
        # With 500k timesteps and max_episode_bars=500: ~1,000 complete episodes vs ~24 without.
        self._max_episode_bars = max_episode_bars
        self._episode_end: int = self.n_bars  # updated each reset()

        self._reward_cfg = {**REWARD_CONFIG, **(reward_config or {})}
        self.discord_context = discord_context  # None → backward-compat zeros at indices 18-22

        params = get_instrument_params(self.symbol)
        self.stc_os = params[0]
        self.stc_ob = params[1]
        self.stop_atr = params[2]
        self.t1_atr = params[3]

        # Gymnasium spaces
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(N_FEATURES,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(N_ACTIONS)

        # Internal state (reset on each episode)
        self._idx: int = 0
        self._position: int = 0  # 1=long, 0=flat, -1=short
        self._entry_price: float = 0.0
        self._bars_in_trade: int = 0
        self._capital: float = initial_capital
        self._episode_pnl: float = 0.0
        self._episode_trades: list[dict] = []
        self._total_reward: float = 0.0
        self._bars_flat: int = 0  # bars where position==0 (for flat_hold_rate)
        self._hold_when_flat: int = 0  # HOLD actions taken while flat
        self._t1_hits: int = 0  # trades that reached T1 target

    # ── Gymnasium interface ───────────────────────────────────────────────

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> tuple[np.ndarray, dict]:
        """Reset environment to start of data. Returns (obs, info)."""
        # Seeding: np.random.seed() and np.random.randint() both operate on
        # NumPy's legacy global RNG — they share the same state, so seeding is
        # consistent and reproducible.  We deliberately avoid np.random.default_rng
        # here because SB3's VecEnv infrastructure calls reset(seed=...) expecting
        # Gymnasium's legacy RNG contract, and mixing the two APIs would break
        # that contract.
        if seed is not None:
            np.random.seed(seed)

        # Random window start — gives diverse training episodes.
        # Keep at least max_episode_bars bars before the end.
        # When the dataset is too small (latest_start <= warm_up), pin start at
        # warm_up so there are always warm_up bars of indicator history available.
        warm_up = 50
        latest_start = max(warm_up, self.n_bars - self._max_episode_bars)
        if latest_start > warm_up:
            self._idx = int(np.random.randint(warm_up, latest_start + 1))
        else:
            self._idx = warm_up
        self._episode_end = min(self._idx + self._max_episode_bars, self.n_bars)

        self._position = 0
        self._entry_price = 0.0
        self._bars_in_trade = 0
        self._capital = self.initial_capital
        self._episode_pnl = 0.0
        self._episode_trades = []
        self._total_reward = 0.0
        self._bars_flat = 0
        self._hold_when_flat = 0
        self._t1_hits = 0

        obs = self._get_obs()
        info = self._get_info()
        return obs, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """
        Execute one step.

        Returns
        -------
        obs        : New observation
        reward     : Step reward
        terminated : True if episode ended (end of data or ruin)
        truncated  : Always False (no time limit truncation)
        info       : Diagnostic dict
        """
        action = int(action)
        row = self.df.iloc[self._idx]
        close = float(row.get("close", 0.0))
        atr = float(row.get("atr", 1.0) or 1.0)

        realized_pnl = 0.0
        is_new_entry = False
        forced_close = False

        # ── Execute action ───────────────────────────────────────────────
        if action == Action.BUY:
            if self._position == 0:
                # Open long
                self._position = 1
                self._entry_price = close
                self._bars_in_trade = 0
                is_new_entry = True
            elif self._position == -1:
                # Close short, then open long
                realized_pnl = (self._entry_price - close) * 1
                self._record_trade(realized_pnl)
                self._position = 1
                self._entry_price = close
                self._bars_in_trade = 0
                is_new_entry = True

        elif action == Action.SELL:
            if self._position == 0:
                # Open short
                self._position = -1
                self._entry_price = close
                self._bars_in_trade = 0
                is_new_entry = True
            elif self._position == 1:
                # Close long, then open short
                realized_pnl = (close - self._entry_price) * 1
                self._record_trade(realized_pnl)
                self._position = -1
                self._entry_price = close
                self._bars_in_trade = 0
                is_new_entry = True

        elif action == Action.CLOSE:
            if self._position == 1:
                realized_pnl = (close - self._entry_price) * 1
                self._record_trade(realized_pnl)
                self._position = 0
                self._entry_price = 0.0
                self._bars_in_trade = 0
            elif self._position == -1:
                realized_pnl = (self._entry_price - close) * 1
                self._record_trade(realized_pnl)
                self._position = 0
                self._entry_price = 0.0
                self._bars_in_trade = 0
        # Action.HOLD: do nothing

        # Increment bars counter for open position
        if self._position != 0:
            self._bars_in_trade += 1

        # Forced close: hard cap on bars in trade (Run 10 — prevents 100+ bar holds)
        if self._position != 0 and self._bars_in_trade >= MAX_BARS_IN_TRADE:
            forced_close = True
            force_close = (
                float(self.df.iloc[self._idx]["close"]) if self._idx < len(self.df) else close
            )
            if self._position == 1:
                forced_pnl = force_close - self._entry_price
            else:
                forced_pnl = self._entry_price - force_close
            realized_pnl += forced_pnl
            self._record_trade(forced_pnl)
            self._position = 0
            self._entry_price = 0.0
            self._bars_in_trade = 0
            logger.debug(
                "Forced close at bar %d — held %d bars (cap=%d), pnl=%.4f",
                self._idx,
                MAX_BARS_IN_TRADE,
                MAX_BARS_IN_TRADE,
                forced_pnl,
            )

        # Track flat-HOLD rate (more meaningful than blended hold_rate)
        if self._position == 0:
            self._bars_flat += 1
            if action == Action.HOLD:
                self._hold_when_flat += 1

        # Update capital
        self._capital += realized_pnl
        self._episode_pnl += realized_pnl

        # ── Reward ───────────────────────────────────────────────────────
        reward = self._calculate_reward(
            action=action,
            realized_pnl=realized_pnl,
            atr=atr,
            is_new_entry=is_new_entry,
            forced_close=forced_close,
        )
        self._total_reward += reward

        # ── Advance bar ──────────────────────────────────────────────────
        self._idx += 1
        terminated = self._idx >= self._episode_end or self._capital <= 0

        # Auto-close position at end of episode
        if terminated and self._position != 0:
            final_close = float(self.df.iloc[self._idx - 1]["close"])
            if self._position == 1:
                realized_pnl = final_close - self._entry_price
            else:
                realized_pnl = self._entry_price - final_close
            self._record_trade(realized_pnl)
            self._capital += realized_pnl
            self._position = 0

        obs = self._get_obs() if not terminated else np.zeros(N_FEATURES, dtype=np.float32)
        info = self._get_info(realized_pnl=realized_pnl, forced_close=forced_close)

        return obs, reward, terminated, False, info

    def render(self) -> None:
        bar = self.df.iloc[min(self._idx, self.n_bars - 1)]
        pos_str = {1: "LONG", 0: "FLAT", -1: "SHORT"}.get(self._position, "?")
        print(
            f"Bar {self._idx:4d} | Close {float(bar['close']):.2f} | "
            f"Pos {pos_str:5s} | PnL {self._episode_pnl:+.2f} | "
            f"Reward {self._total_reward:+.4f}"
        )

    def close(self) -> None:
        pass

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_obs(self) -> np.ndarray:
        idx = min(self._idx, self.n_bars - 1)
        base_obs = extract_features(
            df=self.df,
            idx=idx,
            position=self._position,
            entry_price=self._entry_price,
            bars_in_trade=self._bars_in_trade,
            symbol=self.symbol,
        )

        # Append 5 Discord signal context features (indices 18-22).
        # Falls back to safe defaults when discord_context is None or query fails.
        if self.discord_context is not None:
            try:
                row = self.df.iloc[idx]
                # Resolve timestamp: use DataFrame index if it is datetime-typed
                if hasattr(self.df.index, "dtype") and hasattr(self.df.index[idx], "to_pydatetime"):
                    timestamp = self.df.index[idx].to_pydatetime()
                elif isinstance(self.df.index[idx], datetime):
                    timestamp = self.df.index[idx]
                else:
                    timestamp = datetime.now()
                price = float(row.get("close", row.get("Close", 0.0)))
                atr = float(row.get("atr", 1.0) or 1.0)
                discord_feats = self.discord_context.get_feature_list(
                    symbol=self.symbol,
                    timestamp=timestamp,
                    price=price,
                    atr=atr,
                    jarvis_bias="NEUTRAL",  # can be enhanced later to use regime_score
                )
                discord_arr = np.array(discord_feats, dtype=np.float32)
            except Exception:
                discord_arr = np.array([0.0, 0.5, 0.0, 0.0, 0.0], dtype=np.float32)
        else:
            # No discord context — fill with neutral defaults (0.5 for win rate, 0 elsewhere)
            discord_arr = np.array([0.0, 0.5, 0.0, 0.0, 0.0], dtype=np.float32)

        return np.concatenate([base_obs, discord_arr])

    def _get_info(self, realized_pnl: float = 0.0, forced_close: bool = False) -> dict:
        return {
            "idx": self._idx,
            "position": self._position,
            "entry_price": self._entry_price,
            "bars_in_trade": self._bars_in_trade,
            "capital": self._capital,
            "episode_pnl": self._episode_pnl,
            "realized_pnl": realized_pnl,
            "total_reward": self._total_reward,
            "n_trades": len(self._episode_trades),
            "forced_close": forced_close,
        }

    def _calculate_reward(
        self,
        action: int,
        realized_pnl: float,
        atr: float,
        is_new_entry: bool,
        forced_close: bool = False,
    ) -> float:
        cfg = self._reward_cfg

        # PBR (TensorTrade ML/AI Novel #3): subtract real broker commission from
        # realized_pnl in dollars BEFORE the ATR-normalised reward calculation,
        # so the agent learns to clear the commission floor (~$1.30/contract MCL).
        # Charged only on closing trades (realized_pnl != 0); is_new_entry trades
        # have realized_pnl == 0 and pay nothing here. Defaults to 0.0 to keep
        # legacy training runs reproducible (see rl_config.REWARD_CONFIG).
        commission = (
            cfg.get("commission_usd_per_contract", 0.0)
            * cfg.get("contracts_per_trade", 1)
        )
        if realized_pnl != 0.0 and commission > 0.0:
            realized_pnl = realized_pnl - commission

        # Primary: P&L in ATR units (scale-invariant across instruments)
        pnl_reward = (realized_pnl / atr * cfg["pnl_atr_weight"]) if atr > 0 else 0.0

        # Flat holding cost per bar when in a position (NOT compounding — was a bug)
        # Run 11: when hold_cost_only_when_losing=True, charge hold cost only while
        # position is underwater. Free holds while winning → agent can reach T1.
        if self._position != 0:
            if cfg.get("hold_cost_only_when_losing", False) and self._entry_price > 0:
                current_close = float(self.df.iloc[self._idx]["close"])
                unrealized_pnl = (current_close - self._entry_price) * self._position
                hold_cost = cfg["hold_cost_per_bar"] if unrealized_pnl <= 0 else 0.0
            else:
                hold_cost = cfg["hold_cost_per_bar"]
        else:
            hold_cost = 0.0

        # Small reward for HOLDing when flat — teaches patience, pushes hold_rate up
        flat_hold_reward = (
            cfg.get("flat_hold_reward", 0.0)
            if (action == Action.HOLD and self._position == 0)
            else 0.0
        )

        # Overtrading penalty per new entry
        entry_cost = cfg["entry_cost"] if is_new_entry else 0.0

        # Penalty for redundant/invalid actions: BUY when already long, SELL when already short
        # These are no-ops in the env but agent was discovering them as "free HOLD" — stop that.
        # Guard with `not is_new_entry` so a genuine entry from flat is not double-charged
        # (position is already updated to 1/-1 before this method is called).
        redundant_cost = (
            cfg["entry_cost"]
            if (
                not is_new_entry
                and (
                    (action == Action.BUY and self._position == 1)
                    or (action == Action.SELL and self._position == -1)
                )
            )
            else 0.0
        )

        # Bonus for reaching T1 target
        t1_bonus = 0.0
        if realized_pnl > 0 and atr > 0 and (realized_pnl / atr) >= self.t1_atr:
            t1_bonus = cfg["t1_bonus"]
            self._t1_hits += 1

        # Penalty for forced close at MAX_BARS_IN_TRADE limit (Run 10)
        forced_close_penalty = cfg.get("entry_cost", -0.01) if forced_close else 0.0

        return float(
            pnl_reward
            + hold_cost
            + flat_hold_reward
            + entry_cost
            + redundant_cost
            + t1_bonus
            + forced_close_penalty
        )

    def _record_trade(self, pnl: float) -> None:
        self._episode_trades.append(
            {
                "bar": self._idx,
                "pnl": pnl,
                "bars": self._bars_in_trade,
                "position": self._position,
                "entry_price": self._entry_price,
            }
        )

    # ── Metrics ───────────────────────────────────────────────────────────

    def get_episode_metrics(self) -> dict:
        """Compute episode-level performance metrics."""
        trades = self._episode_trades
        flat_hold_rate = self._hold_when_flat / self._bars_flat if self._bars_flat > 0 else 0.0

        if not trades:
            return {
                "n_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "max_drawdown": 0.0,
                "total_reward": self._total_reward,
                "flat_hold_rate": round(flat_hold_rate, 4),
                "t1_hits": self._t1_hits,
                "t1_hit_rate": 0.0,
                "avg_bars_in_trade": 0.0,
            }

        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        win_rate = len(wins) / len(pnls) if pnls else 0.0

        # Running max drawdown
        equity = self.initial_capital
        peak = equity
        max_dd = 0.0
        for p in pnls:
            equity += p
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        avg_bars_in_trade = round(sum(t.get("bars", 0) for t in trades) / max(len(trades), 1), 1)

        return {
            "n_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "max_drawdown": round(max_dd, 4),
            "total_reward": round(self._total_reward, 4),
            "flat_hold_rate": round(flat_hold_rate, 4),
            "t1_hits": self._t1_hits,
            "t1_hit_rate": round(self._t1_hits / max(len(trades), 1), 4),
            "avg_bars_in_trade": avg_bars_in_trade,
        }


# ── Factory ───────────────────────────────────────────────────────────────────


def prepare_dataframe(
    df: Optional[pd.DataFrame],
    cache_path: Optional[Path] = None,
    force_recompute: bool = False,
) -> pd.DataFrame:
    """
    Run compute_all_indicators on raw OHLCV DataFrame.
    If cache_path is given, saves/loads parquet to avoid recomputing.

    Parameters
    ----------
    df            : Raw OHLCV DataFrame (columns: open, high, low, close, volume).
                    May be None when cache_path exists and force_recompute=False.
    cache_path    : Optional parquet path for caching processed data
    force_recompute: If True, recompute even if cache exists

    Returns
    -------
    DataFrame with all indicator columns added
    """
    if cache_path and Path(cache_path).exists() and not force_recompute:
        logger.info(f"Loading cached indicators from {cache_path}")
        return pd.read_parquet(cache_path)

    if df is None:
        raise ValueError("df_raw is None and no valid cache found — cannot compute indicators")

    logger.info(f"Computing indicators on {len(df)} bars...")
    df_processed = compute_all_indicators(df)
    df_processed = df_processed.dropna(subset=["atr", "stc_val"]).reset_index(drop=True)

    if cache_path:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        df_processed.to_parquet(cache_path, index=False)

    return df_processed


def build_env(
    symbol: str,
    df: pd.DataFrame,
    initial_capital: float = 10_000.0,
    max_position: int = 1,
    max_episode_bars: int = MAX_EPISODE_BARS,
    reward_config: dict | None = None,
    discord_context: Optional[DiscordSignalContext] = None,
) -> "TradingEnvironment":
    """
    Factory: create a TradingEnvironment from a processed DataFrame.

    Parameters
    ----------
    discord_context : Optional DiscordSignalContext. When provided, features 18-22
                      are populated from the Discord signal DB. When None (default),
                      features 18-22 are zeros/neutral — backward compatible.
    """
    return TradingEnvironment(
        symbol=symbol,
        df=df,
        initial_capital=initial_capital,
        max_position=max_position,
        max_episode_bars=max_episode_bars,
        reward_config=reward_config,
        discord_context=discord_context,
    )
