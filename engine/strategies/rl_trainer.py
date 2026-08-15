"""
JARVIS TRADER — RL Training Orchestrator
==========================================
Fetches market data, runs compute_all_indicators, trains PPO agent,
and evaluates on OOS test set.

Usage:
    from strategies.rl_trainer import RLTrainer

    trainer = RLTrainer()
    result = await trainer.train_symbol("MES", timesteps=100_000)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from discord.signal_context import DiscordSignalContext
from strategies.rl_agent import RLTradingAgent
from strategies.rl_config import (
    DEFAULT_INTERVAL,
    MAX_EPISODE_BARS,
    RL_CACHE_DIR,
    RL_MODELS_DIR,
    TEST_LOOKBACK_DAYS,
    TIMESTEPS_DEFAULT,
    TRAIN_LOOKBACK_DAYS,
    VALIDATION_GATES,
)
from strategies.rl_environment import build_env, prepare_dataframe

logger = logging.getLogger(__name__)

# Module-level Discord context singleton (shared across all training runs)
_discord_ctx = DiscordSignalContext()


# ── Stop event (module-level so the API can trigger graceful abort) ───────────

_stop_event: threading.Event = threading.Event()


def request_stop() -> None:
    """Signal active training to stop at the next safe checkpoint."""
    _stop_event.set()


def clear_stop() -> None:
    """Clear stop flag (called at start of each new training run)."""
    _stop_event.clear()


# ── Training state (module-level so the API can poll it) ──────────────────────

_training_status: dict = {
    "running": False,
    "symbol": None,
    "started_at": None,
    "progress_pct": 0,
    "last_result": None,
    "error": None,
    # Walk-forward fields (populated during train_walkforward)
    "walkforward_windows": [],
    "walkforward_n_windows": 0,
    "walkforward_complete": False,
}


def get_training_status() -> dict:
    return dict(_training_status)


class RLTrainer:
    """
    Orchestrates RL agent training for jarvis-trader.

    Responsibilities:
    - Fetch historical OHLCV via MarketDataManager
    - Compute all indicators via compute_all_indicators()
    - Cache processed DataFrame to parquet
    - Split into train/test sets
    - Train PPO agent
    - Evaluate on OOS test set
    - Return metrics dict

    Parameters
    ----------
    data_manager : MarketDataManager instance (injected at startup)
                   If None, falls back to BacktestDataLoader (Polygon-backed).
    """

    def __init__(self, data_manager=None):
        self._data_manager = data_manager

    async def train_symbol(
        self,
        symbol: str,
        interval: str = DEFAULT_INTERVAL,
        timesteps: int = TIMESTEPS_DEFAULT,
        force_recompute: bool = False,
        reward_config: dict | None = None,
    ) -> dict:
        """
        Full training pipeline for one symbol.

        Parameters
        ----------
        symbol         : Futures symbol (MES, MNQ, MCL)
        interval       : Bar interval ('1h', '4h', '1d')
        timesteps      : PPO training timesteps
        force_recompute: Re-fetch + recompute indicators even if cached

        Returns
        -------
        dict with keys: symbol, metrics, model_path, duration_seconds, status
        """
        global _training_status

        _stop_event.clear()  # Clear any previous stop request at start of new run

        _training_status.update(
            {
                "running": True,
                "symbol": symbol,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "progress_pct": 0,
                "error": None,
                "abort_requested": False,
            }
        )

        try:
            # ── 1 & 2. Load from cache or fetch+compute ───────────────────────
            cache_path = RL_CACHE_DIR / f"{symbol}_{interval.replace('/', '_')}.parquet"

            if cache_path.exists() and not force_recompute:
                # Fast path: cache hit — skip raw fetch entirely
                logger.info(f"[RLTrainer] Loading cached data for {symbol} from {cache_path}")
                _training_status["progress_pct"] = 5
                df = await asyncio.to_thread(
                    prepare_dataframe,
                    None,  # df_raw=None signals cache-only load
                    cache_path=cache_path,
                    force_recompute=False,
                )
            else:
                # Cold path: fetch raw data, compute indicators, save cache
                logger.info(f"[RLTrainer] Fetching data for {symbol} ({interval})...")
                _training_status["progress_pct"] = 5

                df_raw = await self._fetch_data(
                    symbol=symbol,
                    interval=interval,
                    lookback_days=TRAIN_LOOKBACK_DAYS,
                )

                if df_raw is None or len(df_raw) < 100:
                    raise ValueError(
                        f"Insufficient data for {symbol}: got {len(df_raw) if df_raw is not None else 0} bars"
                    )

                logger.info(f"[RLTrainer] Fetched {len(df_raw)} bars for {symbol}")
                _training_status["progress_pct"] = 15

                df = await asyncio.to_thread(
                    prepare_dataframe,
                    df_raw,
                    cache_path=cache_path,
                    force_recompute=force_recompute,
                )

            if len(df) < 100:
                raise ValueError(f"Too few valid bars after indicator computation: {len(df)}")

            logger.info(f"[RLTrainer] {len(df)} bars ready (indicators computed)")
            _training_status["progress_pct"] = 25

            # ── 3. Train/test split ──────────────────────────────────────────
            # Use last TEST_LOOKBACK_DAYS bars as test set
            # Approximate: 1h bars → ~252 trading days × 7h = ~1764 bars/year
            bars_per_day = {"1h": 7, "4h": 2, "1d": 1}.get(interval, 7)
            test_bars = TEST_LOOKBACK_DAYS * bars_per_day
            split_idx = max(len(df) - test_bars, len(df) // 2)

            df_train = df.iloc[:split_idx].reset_index(drop=True)
            df_test = df.iloc[split_idx:].reset_index(drop=True)

            logger.info(f"[RLTrainer] Train: {len(df_train)} bars | Test: {len(df_test)} bars")
            _training_status["progress_pct"] = 30

            # ── 4. Build environments ────────────────────────────────────────
            # Use MAX_EPISODE_BARS for training (random window sampling → ~1,000 episodes)
            # Evaluation uses full test set (max_episode_bars=len(df_test) = no windowing)
            train_env = build_env(
                symbol=symbol,
                df=df_train,
                max_episode_bars=MAX_EPISODE_BARS,
                reward_config=reward_config,
                discord_context=_discord_ctx,
            )
            test_env = build_env(
                symbol=symbol,
                df=df_test,
                max_episode_bars=len(df_test),
                discord_context=_discord_ctx,
            )

            # ── 5. Train agent ───────────────────────────────────────────────
            if _stop_event.is_set():
                raise InterruptedError("Training aborted by stop request")

            logger.info(f"[RLTrainer] Training {symbol} for {timesteps:,} timesteps...")
            agent = RLTradingAgent(symbol=symbol, env=train_env)

            training_summary = await asyncio.to_thread(agent.train, timesteps)
            _training_status["progress_pct"] = 80

            # ── 6. Evaluate OOS ──────────────────────────────────────────────
            logger.info(f"[RLTrainer] Evaluating {symbol} on OOS test set...")
            metrics = await asyncio.to_thread(agent.evaluate, test_env, n_episodes=1)
            _training_status["progress_pct"] = 90

            # ── 7. Save model ────────────────────────────────────────────────
            model_path = await asyncio.to_thread(agent.save)
            _training_status["progress_pct"] = 95

            # ── 8. Build result ──────────────────────────────────────────────
            result = {
                "status": "complete",
                "symbol": symbol,
                "interval": interval,
                "timesteps": timesteps,
                "train_bars": len(df_train),
                "test_bars": len(df_test),
                "model_path": f"{model_path}.zip",
                "metrics": metrics,
                "training_summary": training_summary,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

            _training_status.update(
                {
                    "running": False,
                    "progress_pct": 100,
                    "last_result": result,
                }
            )

            passes = metrics.get("passes_validation", False)
            logger.info(
                f"[RLTrainer] {symbol} training complete | "
                f"PF={metrics.get('profit_factor','?')} | "
                f"WR={metrics.get('win_rate','?'):.1%} | "
                f"Validation: {'PASS ✅' if passes else 'FAIL ❌'}"
            )
            return result

        except Exception as exc:
            logger.error(f"[RLTrainer] Training failed for {symbol}: {exc}", exc_info=True)
            _training_status.update(
                {
                    "running": False,
                    "error": str(exc),
                    "progress_pct": 0,
                }
            )
            return {
                "status": "error",
                "symbol": symbol,
                "error": str(exc),
            }

    async def train_walkforward(
        self,
        symbol: str,
        interval: str = DEFAULT_INTERVAL,
        timesteps_per_window: int = TIMESTEPS_DEFAULT,
        n_windows: int = 8,
        window_size_bars: int = None,
        reward_config: dict | None = None,
    ) -> dict:
        """
        8-window rolling walk-forward training.

        Window scheme (n_windows=8, 25% overlap):
          W0: train bars[0:3*test], test bars[3*test:4*test]
          W1: train bars[1*test:4*test], test bars[4*test:5*test]
          ...
          W7: train bars[5*test:8*test], test bars[8*test:9*test]

        Each train window = 3x the test window length, sliding by 1 test
        window per step, so there is a 3-window lookback for every 1-window
        test period and the full dataset is consumed over n_windows steps.

        Returns dict with:
          - windows: list of per-window metrics
          - all_pass: bool (True only if ALL windows pass all gates)
          - aggregate_metrics: averaged metrics across all windows
          - best_model_path: path to model from best window (highest profit factor)
          - recommendation: "deploy" | "retrain" | "reject"
        """
        global _training_status

        _stop_event.clear()  # Clear any previous stop request at start of new run

        _training_status.update(
            {
                "running": True,
                "symbol": symbol,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "progress_pct": 0,
                "error": None,
                "abort_requested": False,
                "walkforward_windows": [],
                "walkforward_n_windows": n_windows,
                "walkforward_complete": False,
            }
        )

        try:
            # ── 1 & 2. Load from cache or fetch+compute ───────────────────────
            cache_path = RL_CACHE_DIR / f"{symbol}_{interval.replace('/', '_')}.parquet"

            if cache_path.exists():
                # Fast path: cache hit — skip raw fetch
                logger.info(
                    f"[RLTrainer.WF] Loading cached data for {symbol} from {cache_path} — "
                    f"{n_windows}-window walk-forward..."
                )
                _training_status["progress_pct"] = 3
                df = await asyncio.to_thread(
                    prepare_dataframe,
                    None,  # df_raw=None signals cache-only load
                    cache_path=cache_path,
                    force_recompute=False,
                )
            else:
                # Cold path: fetch raw data, compute indicators, save cache
                logger.info(
                    f"[RLTrainer.WF] Fetching data for {symbol} ({interval}) — "
                    f"{n_windows}-window walk-forward..."
                )
                _training_status["progress_pct"] = 3

                df_raw = await self._fetch_data(
                    symbol=symbol,
                    interval=interval,
                    lookback_days=TRAIN_LOOKBACK_DAYS,
                )

                if df_raw is None or len(df_raw) < 100:
                    raise ValueError(
                        f"Insufficient data for {symbol}: "
                        f"got {len(df_raw) if df_raw is not None else 0} bars"
                    )

                logger.info(f"[RLTrainer.WF] Fetched {len(df_raw)} bars for {symbol}")
                _training_status["progress_pct"] = 8

                df = await asyncio.to_thread(
                    prepare_dataframe,
                    df_raw,
                    cache_path=cache_path,
                    force_recompute=False,
                )

            if len(df) < 100:
                raise ValueError(f"Too few valid bars after indicator computation: {len(df)}")

            logger.info(f"[RLTrainer.WF] {len(df)} bars ready (indicators computed)")
            _training_status["progress_pct"] = 12

            # ── 3. Calculate window sizes ────────────────────────────────────
            total_bars = len(df)
            if window_size_bars is not None:
                test_bars = window_size_bars
            else:
                # Divide total bars so that n_windows non-overlapping test periods
                # fit after a 3x train lookback prefix.
                # Layout: [3*test] [test]*n_windows  → total = (3 + n_windows) * test
                test_bars = max(50, total_bars // (n_windows + 3))

            train_bars = test_bars * 3

            # Verify we have enough data for at least the first window
            required_bars = train_bars + n_windows * test_bars
            if required_bars > total_bars:
                # Shrink test_bars to fit
                test_bars = max(30, total_bars // (n_windows + 3 + 1))
                train_bars = test_bars * 3
                logger.warning(
                    f"[RLTrainer.WF] Adjusted window sizes: "
                    f"train={train_bars} test={test_bars} bars/window"
                )

            logger.info(
                f"[RLTrainer.WF] Window layout: train={train_bars} bars, "
                f"test={test_bars} bars, {n_windows} windows"
            )

            # ── 4. Run each window ───────────────────────────────────────────
            window_results: list[dict] = []
            best_pf: float = -float("inf")  # track best window by profit_factor
            best_model_path: Optional[str] = None

            for w_idx in range(n_windows):
                # Sliding window: train starts at w_idx * test_bars
                train_start = w_idx * test_bars
                train_end = train_start + train_bars
                test_start = train_end
                test_end = test_start + test_bars

                # Guard: don't exceed dataframe
                if test_end > total_bars:
                    logger.warning(
                        f"[RLTrainer.WF] Window {w_idx} exceeds data bounds — stopping early"
                    )
                    break

                df_train_w = df.iloc[train_start:train_end].reset_index(drop=True)
                df_test_w = df.iloc[test_start:test_end].reset_index(drop=True)

                logger.info(
                    f"[RLTrainer.WF] Window {w_idx}/{n_windows - 1} | "
                    f"train [{train_start}:{train_end}] "
                    f"test [{test_start}:{test_end}]"
                )

                # Check stop before starting this window's blocking train
                if _stop_event.is_set():
                    logger.info("[RL] Training abort requested — stopping walk-forward")
                    break

                # Train + evaluate in a thread (fresh PPO model each window)
                w_result = await asyncio.to_thread(
                    self._train_and_evaluate_window,
                    symbol=symbol,
                    df_train=df_train_w,
                    df_test=df_test_w,
                    timesteps=timesteps_per_window,
                    window_idx=w_idx,
                    reward_config=reward_config,
                )

                # Check stop after each completed window
                if _stop_event.is_set():
                    logger.info(
                        "[RL] Training abort requested — stopping walk-forward after window %d",
                        w_idx,
                    )
                    window_results.append(w_result)
                    _training_status["walkforward_windows"] = list(window_results)
                    break

                # Check validation gates for this window.
                # Gates checked: profit_factor, win_rate, max_drawdown, n_trades,
                # hold_rate (from training action distribution, available after agent.train()).
                # Note: sharpe is NOT returned by get_episode_metrics() and cannot be
                # checked per-window without a separate Sharpe computation step.
                metrics = w_result.get("metrics", {})
                gates = VALIDATION_GATES
                pf = metrics.get("profit_factor", 0.0)
                wr = metrics.get("win_rate", 0.0)
                max_dd = metrics.get("max_drawdown", 1.0)
                n_trades = metrics.get("n_trades", 0)
                hold_rate = metrics.get("hold_rate", 0.0)

                window_pass = all(
                    [
                        pf >= gates["min_profit_factor"],
                        wr >= gates["min_win_rate"],
                        max_dd <= gates["max_drawdown"],
                        n_trades >= gates["min_trades"],
                        hold_rate >= gates["min_hold_rate"],
                    ]
                )
                w_result["window_pass"] = window_pass
                w_result["window_idx"] = w_idx
                w_result["train_start"] = train_start
                w_result["train_end"] = train_end
                w_result["test_start"] = test_start
                w_result["test_end"] = test_end

                window_results.append(w_result)

                # Update live status so API can stream progress
                _training_status["walkforward_windows"] = list(window_results)

                # Track best model by profit_factor (sharpe not available from env metrics)
                if pf > best_pf and w_result.get("model_path"):
                    best_pf = pf
                    best_model_path = w_result["model_path"]

                # Progress: windows consume pct 12→90
                progress = 12 + int(78 * (w_idx + 1) / n_windows)
                _training_status["progress_pct"] = progress

                logger.info(
                    f"[RLTrainer.WF] Window {w_idx} {'PASS' if window_pass else 'FAIL'} | "
                    f"PF={pf:.2f} WR={wr:.1%} MaxDD={max_dd:.1%} "
                    f"Trades={n_trades} HoldRate={hold_rate:.1%}"
                )

            # ── 5. Aggregate metrics across all windows ──────────────────────
            _training_status["progress_pct"] = 92

            if not window_results:
                raise ValueError("No windows completed — check data size")

            all_metrics_keys = window_results[0].get("metrics", {}).keys()
            aggregate_metrics: dict = {}
            for k in all_metrics_keys:
                vals = [w["metrics"].get(k, 0.0) for w in window_results]
                try:
                    aggregate_metrics[k] = round(float(sum(vals) / len(vals)), 4)
                except (TypeError, ValueError):
                    aggregate_metrics[k] = vals[-1]  # fallback for non-numeric

            all_pass = all(w["window_pass"] for w in window_results)

            # ── 6. Copy best model to a stable "walkforward_best" path ───────
            _training_status["progress_pct"] = 95

            walkforward_best_path: Optional[str] = None
            if best_model_path is not None:
                import shutil

                RL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
                dest_stem = str(RL_MODELS_DIR / f"{symbol.upper()}_walkforward_best")
                src_zip = f"{best_model_path}.zip"
                dest_zip = f"{dest_stem}.zip"
                if src_zip != dest_zip:
                    try:
                        shutil.copy2(src_zip, dest_zip)
                        logger.info(
                            f"[RLTrainer.WF] Best model (PF={best_pf:.2f}) " f"saved to {dest_zip}"
                        )
                    except Exception as copy_err:
                        logger.warning(f"[RLTrainer.WF] Could not copy best model: {copy_err}")
                walkforward_best_path = dest_zip

            # ── 7. Derive recommendation ─────────────────────────────────────
            n_pass = sum(1 for w in window_results if w["window_pass"])
            pass_rate = n_pass / len(window_results)

            if all_pass:
                recommendation = "deploy"
            elif pass_rate >= 0.75:
                recommendation = "retrain"
            else:
                recommendation = "reject"

            # ── 7b. Compute WFE = mean_oos_pf / mean_is_pf ──────────────────
            oos_pfs = [w["metrics"].get("profit_factor", 0.0) for w in window_results]
            is_pfs = [w.get("is_metrics", {}).get("profit_factor", 0.0) for w in window_results]
            mean_oos_pf = sum(oos_pfs) / max(len(oos_pfs), 1)
            mean_is_pf = sum(is_pfs) / max(len(is_pfs), 1)
            if mean_is_pf <= 0.0:
                wfe = 0.0
            else:
                wfe = min(max(mean_oos_pf / mean_is_pf, 0.0), 2.0)
            wfe = round(wfe, 4)

            logger.info(
                f"[RLTrainer.WF] WFE={wfe:.2f} "
                f"(OOS_PF={mean_oos_pf:.2f} / IS_PF={mean_is_pf:.2f})"
            )

            # ── 8. Build final result ────────────────────────────────────────
            result = {
                "status": "complete",
                "symbol": symbol,
                "interval": interval,
                "timesteps_per_window": timesteps_per_window,
                "n_windows": len(window_results),
                "windows": window_results,
                "all_pass": all_pass,
                "pass_rate": round(pass_rate, 4),
                "wfe": wfe,
                "aggregate_metrics": aggregate_metrics,
                "best_model_path": walkforward_best_path,
                "recommendation": recommendation,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

            _training_status.update(
                {
                    "running": False,
                    "progress_pct": 100,
                    "last_result": result,
                    "walkforward_complete": True,
                }
            )

            logger.info(
                f"[RLTrainer.WF] Walk-forward complete for {symbol} | "
                f"{n_pass}/{len(window_results)} windows pass | "
                f"Recommendation: {recommendation.upper()}"
            )
            return result

        except Exception as exc:
            logger.error(
                f"[RLTrainer.WF] Walk-forward failed for {symbol}: {exc}",
                exc_info=True,
            )
            _training_status.update(
                {
                    "running": False,
                    "error": str(exc),
                    "progress_pct": 0,
                    "walkforward_complete": False,
                }
            )
            return {
                "status": "error",
                "symbol": symbol,
                "error": str(exc),
            }

    def _train_and_evaluate_window(
        self,
        symbol: str,
        df_train: pd.DataFrame,
        df_test: pd.DataFrame,
        timesteps: int,
        window_idx: int,
        reward_config: dict | None = None,
        discord_context=None,
    ) -> dict:
        """
        Synchronous train + evaluate for a single walk-forward window.

        Called via asyncio.to_thread() so it doesn't block the event loop.
        Returns a dict with keys: metrics, model_path, train_bars, test_bars,
        training_summary.
        """
        from strategies.rl_agent import RLTradingAgent

        train_env = build_env(
            symbol=symbol,
            df=df_train,
            max_episode_bars=MAX_EPISODE_BARS,
            reward_config=reward_config,
            discord_context=discord_context,
        )
        test_env = build_env(
            symbol=symbol,
            df=df_test,
            max_episode_bars=len(df_test),
            discord_context=discord_context,
        )

        agent = RLTradingAgent(symbol=symbol, env=train_env)
        training_summary = agent.train(timesteps)

        metrics = agent.evaluate(test_env, n_episodes=1)

        # IS evaluation — evaluate trained agent on full training data to get IS profit_factor
        # Used by train_walkforward to compute WFE = avg(OOS_pf) / avg(IS_pf)
        try:
            is_eval_env = build_env(
                symbol=symbol,
                df=df_train,
                max_episode_bars=len(df_train),
                discord_context=discord_context,
            )
            is_metrics = agent.evaluate(is_eval_env, n_episodes=1)
        except Exception as is_err:
            logger.warning(f"[RLTrainer.WF] Window {window_idx} IS eval failed: {is_err}")
            is_metrics = {}

        # Save this window's model so best can be identified later
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        RL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_path = str(RL_MODELS_DIR / f"{symbol.upper()}_wf_w{window_idx:02d}_{timestamp}")
        try:
            agent.save(model_path)
        except Exception as save_err:
            logger.warning(f"[RLTrainer.WF] Window {window_idx} model save failed: {save_err}")
            model_path = None

        return {
            "train_bars": len(df_train),
            "test_bars": len(df_test),
            "metrics": metrics,
            "is_metrics": is_metrics,
            "model_path": model_path,
            "training_summary": training_summary,
        }

    async def _fetch_data(
        self,
        symbol: str,
        interval: str,
        lookback_days: int,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data.

        Priority:
        1. MarketDataManager (IBKR → Polygon) if injected
        2. BacktestDataLoader (Polygon + CSV cache) as fallback
        """
        if self._data_manager is not None:
            try:
                df = await self._data_manager.get_bars(
                    symbol=symbol,
                    lookback_days=lookback_days,
                    timeframe=interval,
                    is_futures=True,
                )
                if df is not None and len(df) >= 50:
                    return self._normalize_columns(df)
            except Exception as e:
                logger.warning(
                    f"[RLTrainer] MarketDataManager failed: {e} — falling back to BacktestDataLoader"
                )

        # BacktestDataLoader fallback (Polygon-backed, CSV-cached)
        return await asyncio.to_thread(self._fetch_via_loader, symbol, lookback_days, interval)

    def _fetch_via_loader(
        self,
        symbol: str,
        lookback_days: int,
        interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch via BacktestDataLoader as fallback."""
        try:
            from datetime import datetime, timedelta

            from backtest.data_loader import BacktestDataLoader

            end_date = datetime.utcnow().strftime("%Y-%m-%d")
            start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

            loader = BacktestDataLoader()
            df = loader.load(symbol, start_date, end_date, interval)

            if df is None or df.empty:
                logger.warning(
                    f"[RLTrainer] BacktestDataLoader returned empty DataFrame for {symbol}"
                )
                return None

            df = df.reset_index(drop=True)
            return self._normalize_columns(df)

        except Exception as e:
            logger.error(f"[RLTrainer] BacktestDataLoader fetch failed: {e}")
            return None

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure consistent lowercase OHLCV column names."""
        rename = {}
        for col in df.columns:
            lower = col.lower()
            if lower in ("open", "high", "low", "close", "volume"):
                rename[col] = lower
        if rename:
            df = df.rename(columns=rename)
        return df[["open", "high", "low", "close", "volume"]].copy()

    # ── Model listing ─────────────────────────────────────────────────────

    def list_models(self, symbol: Optional[str] = None) -> list[dict]:
        """
        List saved RL models. Optionally filter by symbol.

        Each entry: run_id, symbol, path (model file without .zip extension,
        matches the DeployRequest.model_path / EvaluateRequest.model_path
        convention used elsewhere in this module), size_kb (real .zip file
        size on disk), completed, metadata (training summary sidecar JSON
        when present). symbol/path/size_kb are consumed by the dashboard's
        SavedModel type (dashboard/app/strategies/page.tsx) — sourced here
        from the actual filename and filesystem stat, not fabricated.
        """
        import json

        models_dir = RL_MODELS_DIR
        if not models_dir.exists():
            return []

        results = []
        for zip_path in sorted(models_dir.glob("*.zip"), reverse=True):
            stem = zip_path.stem
            parts = stem.split("_", 1)
            model_symbol = parts[0] if parts else "UNKNOWN"

            if symbol and model_symbol.upper() != symbol.upper():
                continue

            meta = {}
            meta_path = zip_path.with_suffix(".json")
            if meta_path.exists():
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                except Exception:
                    pass

            results.append(
                {
                    "run_id": stem,
                    "symbol": model_symbol,
                    "path": str(zip_path.with_suffix("")),
                    "size_kb": round(zip_path.stat().st_size / 1024, 1),
                    "completed": True,
                    "metadata": meta,
                }
            )

        return results
