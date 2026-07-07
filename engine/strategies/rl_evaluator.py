"""
JARVIS TRADER — RL Out-of-Sample Evaluator
============================================
Loads a saved PPO model and evaluates it on a specified date range,
returning full performance metrics without any training exploration.

Usage:
    from strategies.rl_evaluator import OOSEvaluator

    evaluator = OOSEvaluator(model_path="data/rl_models/MES_20260401_120000")
    metrics = evaluator.evaluate("MES", "2025-10-01", "2026-04-01")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from strategies.rl_config import (
    DEFAULT_INTERVAL,
    RL_MODELS_DIR,
    VALIDATION_GATES,
)
from strategies.rl_environment import TradingEnvironment, build_env, prepare_dataframe

logger = logging.getLogger(__name__)


class OOSEvaluator:
    """
    Out-of-sample evaluator for a saved RL trading agent.

    Loads a pre-trained PPO model and runs deterministic inference
    (no exploration) over a user-specified date range, computing
    full performance metrics.

    Parameters
    ----------
    model_path : Path to saved model file (with or without .zip extension).
                 If None, the most recent model for the symbol is found automatically.
    config     : Optional dict for future configuration overrides (reserved).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        config: Optional[dict] = None,
    ):
        self.model_path = model_path
        self.config = config or {}
        self._loaded_model = None
        self._loaded_symbol: Optional[str] = None

    # ── Public API ────────────────────────────────────────────────────────

    def evaluate(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = DEFAULT_INTERVAL,
        data_manager=None,
    ) -> dict:
        """
        Load saved model and run deterministic evaluation on date range.

        Parameters
        ----------
        symbol     : Futures symbol (MES, MNQ, MCL)
        start_date : ISO date string, e.g. "2025-10-01"
        end_date   : ISO date string, e.g. "2026-04-01"
        interval   : Bar interval for data (default "1h")
        data_manager: Optional MarketDataManager for data fetching.
                      Falls back to BacktestDataLoader when None.

        Returns
        -------
        dict with keys:
            symbol, start_date, end_date, n_bars,
            sharpe, profit_factor, win_rate, max_drawdown,
            hold_rate, n_trades, total_pnl, avg_pnl,
            passes_validation, evaluated_at
        """
        logger.info(f"[OOSEvaluator] Evaluating {symbol} from {start_date} to {end_date}")
        start_dt = datetime.now(timezone.utc)

        # ── 1. Resolve model path ────────────────────────────────────────
        model_path = self._resolve_model_path(symbol)
        if model_path is None:
            raise FileNotFoundError(
                f"No saved model found for {symbol}. "
                f"Train first via POST /api/v1/strategies/rl/train."
            )

        # ── 2. Fetch + prepare data ──────────────────────────────────────
        df_raw = self._fetch_data(
            symbol=symbol,
            interval=interval,
            data_manager=data_manager,
        )
        if df_raw is None or len(df_raw) < 60:
            raise ValueError(
                f"Insufficient data for {symbol}: got "
                f"{len(df_raw) if df_raw is not None else 0} bars"
            )

        df = prepare_dataframe(df_raw)

        # ── 3. Filter to date range ──────────────────────────────────────
        df_range = self._filter_date_range(df, start_date, end_date)
        if len(df_range) < 60:
            raise ValueError(f"Too few bars in range {start_date}→{end_date}: {len(df_range)} bars")

        logger.info(f"[OOSEvaluator] {len(df_range)} bars in evaluation range for {symbol}")

        # ── 4. Build environment ─────────────────────────────────────────
        env = build_env(symbol=symbol, df=df_range)

        # ── 5. Load model ─────────────────────────────────────────────────
        ppo_model = self._load_model(model_path, env)

        # ── 6. Run deterministic episode ─────────────────────────────────
        action_counts = {0: 0, 1: 0, 2: 0, 3: 0}  # HOLD, BUY, SELL, CLOSE
        obs, _ = env.reset()
        done = False

        while not done:
            action, _ = ppo_model.predict(np.array(obs, dtype=np.float32), deterministic=True)
            action = int(action)
            action_counts[action] = action_counts.get(action, 0) + 1
            obs, _reward, terminated, truncated, _info = env.step(action)
            done = terminated or truncated

        # ── 7. Compute metrics ───────────────────────────────────────────
        episode_metrics = env.get_episode_metrics()

        total_actions = sum(action_counts.values()) or 1
        hold_rate = round(action_counts[0] / total_actions, 4)

        # Sharpe: approximate from daily-equivalent P&L series
        sharpe = self._compute_sharpe(env)

        gates = VALIDATION_GATES
        pf = episode_metrics.get("profit_factor", 0.0)
        wr = episode_metrics.get("win_rate", 0.0)
        max_dd = episode_metrics.get("max_drawdown", 1.0)
        n_trades = episode_metrics.get("n_trades", 0)
        avg_bars_in_trade = episode_metrics.get("avg_bars_in_trade", 0.0)
        t1_hit_rate = episode_metrics.get("t1_hit_rate", 0.0)

        passes_validation = all(
            [
                pf >= gates["min_profit_factor"],
                wr >= gates["min_win_rate"],
                max_dd <= gates["max_drawdown"],
                n_trades >= gates["min_trades"],
                hold_rate >= gates["min_hold_rate"],
                sharpe >= gates["min_sharpe"],
            ]
        )

        # Run 10 gate checks: avg_bars_in_trade < 50, t1_hit_rate > 0.05
        avg_bars_gate_pass = avg_bars_in_trade < 50
        t1_hit_rate_gate_pass = t1_hit_rate > 0.05
        gate_status = "PASS" if (avg_bars_gate_pass and t1_hit_rate_gate_pass) else "FAIL"
        logger.info(
            f"[OOSEvaluator] Run 10 gates: "
            f"avg_bars_in_trade={avg_bars_in_trade:.1f} {'PASS' if avg_bars_gate_pass else 'FAIL'} | "
            f"t1_hit_rate={t1_hit_rate:.1%} {'PASS' if t1_hit_rate_gate_pass else 'FAIL'} | "
            f"Overall: {gate_status}"
        )

        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()

        result = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "interval": interval,
            "model_path": str(model_path),
            "n_bars": len(df_range),
            "sharpe": round(sharpe, 4),
            "profit_factor": round(pf, 4),
            "win_rate": round(wr, 4),
            "max_drawdown": round(max_dd, 4),
            "hold_rate": hold_rate,
            "n_trades": n_trades,
            "total_pnl": episode_metrics.get("total_pnl", 0.0),
            "avg_pnl": episode_metrics.get("avg_pnl", 0.0),
            "avg_bars_in_trade": round(avg_bars_in_trade, 1),
            "t1_hit_rate": round(t1_hit_rate, 4),
            "action_distribution": {
                "HOLD": round(action_counts[0] / total_actions, 4),
                "BUY": round(action_counts[1] / total_actions, 4),
                "SELL": round(action_counts[2] / total_actions, 4),
                "CLOSE": round(action_counts[3] / total_actions, 4),
            },
            "passes_validation": passes_validation,
            "elapsed_seconds": round(elapsed, 2),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"[OOSEvaluator] {symbol} evaluation complete | "
            f"PF={pf:.2f} | WR={wr:.1%} | HOLD={hold_rate:.1%} | "
            f"Validation: {'PASS' if passes_validation else 'FAIL'}"
        )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _resolve_model_path(self, symbol: str) -> Optional[Path]:
        """Return model path. Uses self.model_path if provided, else finds latest."""
        if self.model_path:
            p = Path(self.model_path)
            # stable-baselines3 saves as .zip; accept path with or without extension
            if p.exists():
                return p
            zip_p = Path(str(self.model_path) + ".zip")
            if zip_p.exists():
                return p  # PPO.load accepts path without .zip
            logger.warning(f"[OOSEvaluator] model_path not found: {self.model_path}")

        # Auto-find latest model for symbol
        models_dir = RL_MODELS_DIR
        if not models_dir.exists():
            return None

        candidates = sorted(
            models_dir.glob(f"{symbol.upper()}_*.zip"),
            reverse=True,  # newest first (lexicographic on timestamp suffix)
        )
        if candidates:
            path_no_ext = candidates[0].with_suffix("")
            logger.info(f"[OOSEvaluator] Auto-resolved model: {candidates[0]}")
            return path_no_ext

        return None

    def _load_model(self, model_path: Path, env: TradingEnvironment):
        """Load PPO model from disk."""
        try:
            from stable_baselines3 import PPO
        except ImportError as exc:
            raise ImportError(
                "stable-baselines3 is required: pip install stable-baselines3"
            ) from exc

        logger.info(f"[OOSEvaluator] Loading model from {model_path}")
        return PPO.load(str(model_path), env=env)

    def _fetch_data(
        self,
        symbol: str,
        interval: str,
        data_manager=None,
    ) -> Optional[pd.DataFrame]:
        """Fetch raw OHLCV data. Uses data_manager if provided, else BacktestDataLoader."""
        if data_manager is not None:
            try:
                import asyncio

                df = asyncio.run(
                    data_manager.get_bars(
                        symbol=symbol,
                        lookback_days=730,
                        timeframe=interval,
                        is_futures=True,
                    )
                )
                if df is not None and len(df) >= 60:
                    return self._normalize_columns(df)
            except Exception as exc:
                logger.warning(
                    f"[OOSEvaluator] data_manager fetch failed: {exc}, trying BacktestDataLoader"
                )

        return self._fetch_via_loader(symbol, lookback_days=730, interval=interval)

    def _fetch_via_loader(
        self,
        symbol: str,
        lookback_days: int,
        interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch via BacktestDataLoader (Polygon → CSV cache)."""
        try:
            from datetime import datetime, timedelta

            from backtest.data_loader import BacktestDataLoader

            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            loader = BacktestDataLoader()
            df = loader.load(symbol, start, end, interval=interval)
            if df is not None and len(df) >= 60:
                return self._normalize_columns(df)
        except Exception as exc:
            logger.error(f"[OOSEvaluator] BacktestDataLoader fetch failed: {exc}")
        return None

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure lowercase OHLCV column names."""
        rename = {
            col: col.lower()
            for col in df.columns
            if col.lower() in ("open", "high", "low", "close", "volume")
        }
        if rename:
            df = df.rename(columns=rename)
        return df[["open", "high", "low", "close", "volume"]].copy()

    def _filter_date_range(
        self,
        df: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Filter DataFrame to the specified date range.
        If df has no DatetimeIndex, use a tail-based heuristic.
        """
        if isinstance(df.index, pd.DatetimeIndex):
            mask = (df.index >= start_date) & (df.index <= end_date)
            return df.loc[mask].reset_index(drop=True)

        # No date index — use last N bars as proxy (OOS portion)
        # Approximate 1h bars: ~7 bars/trading day
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            days = max((end_dt - start_dt).days, 1)
            bars = days * 7
            return df.tail(bars).reset_index(drop=True)
        except Exception:
            return df.reset_index(drop=True)

    def _compute_sharpe(self, env: TradingEnvironment) -> float:
        """
        Approximate annualised Sharpe from episode trade P&L.
        Uses per-trade returns against initial capital.
        """
        trades = env._episode_trades
        if not trades or len(trades) < 2:
            return 0.0

        returns = np.array([t["pnl"] / env.initial_capital for t in trades])
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns))

        if std_r < 1e-9:
            return 0.0

        # Annualise: assume ~252 trades/year heuristic
        sharpe = (mean_r / std_r) * np.sqrt(252)
        return round(float(sharpe), 4)
