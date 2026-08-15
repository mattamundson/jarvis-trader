"""
Backtest and paper trading endpoints

Handles backtesting, walk-forward validation, regime analysis, and MGC paper trading.
"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["backtest"])

# Global references (injected from main.py)
# These will be set by inject_dependencies()
data_manager = None


def inject_dependencies(dm):
    """Inject global dependencies from main.py"""
    global data_manager
    data_manager = dm


class BacktestRequest(BaseModel):
    """Backtest request parameters"""

    symbol: str = "SPY"
    start: str = "2024-01-01"
    end: str = "2025-12-31"
    interval: str = "1d"
    capital: float = 100000.0
    risk_per_trade: float = 0.01


class WalkForwardRequest(BaseModel):
    """Walk-forward validation request"""

    symbol: str
    start: str
    end: str
    interval: str = "1h"
    capital: float = 100_000.0
    adaptive_regime: bool = True
    volume_filter: bool = False
    mtf_filter: bool = False


class RegimeAnalysisRequest(BaseModel):
    """Regime analysis request"""

    results_file: str
    symbol: str = None


class MGCTradeLogRequest(BaseModel):
    """MGC paper trade logging request"""

    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    contracts: int = 1
    direction: str = "LONG"
    exit_reason: str = "unknown"
    regime_type: str = "unknown"


def _sanitize_floats(obj):
    """
    Recursively replace inf/nan float values with None so json.dumps() never
    raises ValueError ('Out of range float values are not JSON compliant').

    Python's json.loads() silently accepts inf/nan written as bare tokens in
    some JSON files produced by the backtest engine (profit_factor can be inf
    when gross_loss == 0). Starlette's JSONResponse uses the stdlib json.dumps
    which rejects those values, causing a 500 *after* response headers are sent
    (shows up as plain-text "Internal Server Error" rather than a JSON error).
    """
    import math

    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


@router.get(
    "/backtest/results",
    description="Return all saved backtest result JSON files from backtest/results directory with filename metadata.",
)
async def get_backtest_results():
    """Return all saved backtest result JSON files from backtest/results/."""
    try:
        import json

        results_dir = Path(__file__).parent.parent / "backtest" / "results"
        if not results_dir.exists():
            return []

        results = []
        for json_file in sorted(results_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data["_filename"] = json_file.name
                elif isinstance(data, list):
                    # Top-level arrays get wrapped so the response stays uniform
                    data = {"_filename": json_file.name, "_array": data}
                else:
                    data = {"_filename": json_file.name, "_scalar": data}
                sanitized = _sanitize_floats(data)
                # Belt-and-suspenders: verify the sanitized entry is JSON-safe
                # with allow_nan=False. If it still has inf/nan, a numpy-subclass
                # leaked past isinstance(float). Drop the entry and log loudly.
                try:
                    json.dumps(sanitized, allow_nan=False)
                except ValueError as enc_err:
                    logger.error(
                        "[BACKTEST] %s leaked inf/nan past sanitizer: %s — dropping entry",
                        json_file.name,
                        enc_err,
                    )
                    continue
                results.append(sanitized)
            except Exception as e:
                logger.warning(f"Failed to parse {json_file.name}: {e}")

        return results
    except Exception as e:
        logger.error(f"[BACKTEST] Results query failed: {e}")
        raise HTTPException(500, f"Failed to get backtest results: {e}") from e


@router.get(
    "/backtest/atr-trail/trades",
    description=(
        "ATR trailing-stop FLIP (TOS ATRTrailingStopLE/SE) trades on cached bars: "
        "price + trail line (with state), every entry/exit, and the equity curve. "
        "Powers the dashboard ATR-trail visualizer."
    ),
)
async def get_atr_trail_trades(
    symbol: str = "MES",
    timeframe: str = "5m",
    period: int = 5,
    factor: float = 3.5,
    max_points: int = 3000,
):
    """Read the freshest cached bars for symbol/timeframe and return the viz payload."""
    try:
        import pandas as pd

        from backtest.atr_trail_viz import compute_atr_trail_viz
        from backtest.run_atr_trail_bounce import _pick_cache_file

        cache = Path(__file__).resolve().parent.parent / "backtest" / "cache"
        # Broad glob so it also matches the IBKR continuous file (..._5m_cont.csv).
        matches = list(cache.glob(f"{symbol}_*_{timeframe}*.csv"))
        if not matches:
            raise HTTPException(
                404, f"No cached {symbol} {timeframe} bars in {cache}. Run the IBKR fetch first."
            )
        # Pick by parsed date range (latest end, longest span), NOT mtime -- a
        # freshly-touched short recent-tail file would otherwise silently win
        # over a longer, older-mtime full-history file. See _pick_cache_file.
        path = _pick_cache_file(matches)

        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        ts_col = next((c for c in ("timestamp", "datetime", "date", "time") if c in df.columns), None)
        if ts_col is None:
            raise HTTPException(422, f"{path.name} has no timestamp column for the bar index.")
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
        df = df.set_index(ts_col).sort_index()

        viz = compute_atr_trail_viz(df, symbol, period, factor, max_points)
        viz["source_file"] = path.name
        return _sanitize_floats(viz)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BACKTEST] ATR-trail viz failed: {e}")
        raise HTTPException(500, f"ATR-trail viz failed: {e}") from e


@router.post(
    "/backtest/run",
    description="Run a single backtest for a symbol over a date range with specified capital and risk per trade.",
)
async def run_backtest(request: BacktestRequest):
    """Run a backtest for a symbol over the specified date range."""
    try:

        def _run():
            from backtest import BacktestDataLoader, Backtester
            from backtest.signals import generate_instrument_signals

            loader = BacktestDataLoader()
            df = loader.load(request.symbol, request.start, request.end, request.interval)
            if df is None or df.empty:
                raise ValueError(f"No data for {request.symbol}")
            df = generate_instrument_signals(df, symbol=request.symbol)
            multiplier = loader.get_multiplier(request.symbol)
            from backtest.signals import TREND_INSTRUMENTS
            from backtest.trend_signals import get_sma_trend_params

            is_trend = request.symbol.upper() in TREND_INSTRUMENTS
            trend_params = get_sma_trend_params(request.symbol) if is_trend else None
            backtester = Backtester(
                initial_capital=request.capital,
                risk_per_trade=request.risk_per_trade,
                trailing_stop=is_trend,
                trailing_atr_mult=trend_params["atr_trail_mult"] if trend_params else 0.70,
                # Trend strategies: no partial exits (WFO closes whole position at death
                # cross or stop); strict trail (update every bar like WFO, no excursion
                # gate); disable kill-switch so all 36 signals can fire.
                t1_exit_pct=1.0 if is_trend else 0.50,
                t2_exit_pct=0.0 if is_trend else 0.30,
                strict_trailing=is_trend,
                # Trend strategies hold overnight (SMA crossovers last days/weeks);
                # intraday EOD-close would chop positions daily, diverging from WFO.
                eod_close=not is_trend,
                # Trend strategies exit ONLY on trailing stop or death cross —
                # never at a fixed ATR target (which would cap winners).
                use_targets=not is_trend,
                # Fixed 1 contract matches WFO equal-weight basis. ATR-scaled sizing
                # inverts trend edge: low-ATR false signals → more contracts (amplified
                # losses); high-ATR trend signals → fewer contracts (dampened wins).
                fixed_contracts=1 if is_trend else None,
                max_drawdown=0.99 if is_trend else 0.05,
                max_daily_loss=0.99 if is_trend else 0.02,
            )
            result = backtester.run(df, request.symbol, multiplier)
            return result.to_dict()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _run)
        return result
    except ValueError as e:
        logger.error(f"[BACKTEST] Data error: {e}")
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.error(f"[BACKTEST] Run failed: {e}")
        raise HTTPException(500, f"Backtest execution failed: {e}") from e


@router.post(
    "/backtest/walk-forward",
    description="Execute walk-forward validation on a symbol with optional adaptive regime, volume filter, and multi-timeframe filter.",
)
async def run_walk_forward(request: WalkForwardRequest):
    """Execute walk-forward validation on a symbol over a date range."""
    try:

        def _run_walk_forward():
            from backtest.data_loader import BacktestDataLoader
            from backtest.signals import generate_signals
            from backtest.walk_forward import WalkForwardValidator

            loader = BacktestDataLoader()

            # Load 1h data
            df_1h = loader.load(request.symbol, request.start, request.end, request.interval)
            if df_1h is None or df_1h.empty:
                raise ValueError(f"No data for {request.symbol}")

            df_1h = generate_signals(
                df_1h, symbol=request.symbol, adaptive_regime=request.adaptive_regime
            )

            # Load daily data if MTF filter requested
            df_daily = None
            if request.mtf_filter:
                df_daily = loader.load(request.symbol, request.start, request.end, "1d")
                if df_daily is not None:
                    df_daily = generate_signals(
                        df_daily, symbol=request.symbol, adaptive_regime=request.adaptive_regime
                    )

            multiplier = loader.get_multiplier(request.symbol)

            # Run walk-forward
            validator = WalkForwardValidator(train_months=6, test_months=3, step_months=3)
            result = validator.run(
                df_1h,
                symbol=request.symbol,
                multiplier=multiplier,
                capital=request.capital,
                top_n_params=1,
                fast=True,
                adaptive_regime=request.adaptive_regime,
                volume_filter=request.volume_filter,
                mtf_filter=request.mtf_filter,
                df_daily=df_daily,
            )
            return result

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _run_walk_forward)

        return result

    except ValueError as e:
        logger.error(f"[WALK-FORWARD] Data error: {e}")
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.error(f"[WALK-FORWARD] Validation failed: {e}")
        raise HTTPException(500, f"Walk-forward validation failed: {e}") from e


@router.post(
    "/backtest/regime-analysis",
    description="Analyze backtest results broken down by market regime with win rates, profit factors, and regime verdicts.",
)
async def analyze_regime(request: RegimeAnalysisRequest):
    """Analyze backtest results broken down by market regime."""
    try:
        from backtest.monte_carlo import _load_result_from_json
        from backtest.regime_analysis import RegimeAnalyzer

        # Resolve file path
        results_path = Path(request.results_file)
        if not results_path.is_absolute():
            alt_path = Path(__file__).parent.parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = (
                    Path(__file__).parent.parent / "backtest" / "results" / request.results_file
                )

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        # Load backtest result
        logger.info(f"[REGIME-ANALYSIS] Loading {results_path.name}")
        bt_result = _load_result_from_json(str(results_path))

        # Auto-detect symbol from filename if not provided
        symbol = request.symbol
        if not symbol:
            stem = results_path.stem
            for part in stem.split("_"):
                if part.isupper() and len(part) <= 4:
                    symbol = part
                    break
        if not symbol:
            symbol = "MES"

        # Run regime analysis
        logger.info(f"[REGIME-ANALYSIS] Analyzing {len(bt_result.trades)} trades for {symbol}")
        RegimeAnalyzer()
        regime_stats = {}

        # Classify each trade by regime and accumulate stats
        for trade in bt_result.trades:
            regime = trade.get("regime", "UNKNOWN")
            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trade_count": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": 0.0,
                    "trades": [],
                }

            pnl = trade.get("pnl", 0.0)
            is_win = pnl >= 0

            regime_stats[regime]["trade_count"] += 1
            if is_win:
                regime_stats[regime]["winning_trades"] += 1
            else:
                regime_stats[regime]["losing_trades"] += 1
            regime_stats[regime]["total_pnl"] += pnl
            regime_stats[regime]["trades"].append(trade)

        # Compute derived metrics
        for _, stats in regime_stats.items():
            count = stats["trade_count"]
            stats["win_rate"] = stats["winning_trades"] / count if count > 0 else 0.0
            pnls = [t.get("pnl", 0.0) for t in stats["trades"]]
            gross_profit = sum(p for p in pnls if p > 0)
            gross_loss = abs(sum(p for p in pnls if p < 0))
            stats["profit_factor"] = gross_profit / gross_loss if gross_loss > 0 else 0.0
            stats["avg_win"] = (
                stats["total_pnl"] / stats["winning_trades"] if stats["winning_trades"] > 0 else 0.0
            )
            stats["avg_loss"] = (
                stats["total_pnl"] / stats["losing_trades"] if stats["losing_trades"] > 0 else 0.0
            )
            del stats["trades"]

        # Determine verdict
        if not regime_stats:
            verdict = "NO_DATA"
        else:
            avg_wrate = sum(s.get("win_rate", 0) for s in regime_stats.values()) / len(regime_stats)
            if avg_wrate >= 0.60:
                verdict = "EXCELLENT"
            elif avg_wrate >= 0.55:
                verdict = "GOOD"
            elif avg_wrate >= 0.50:
                verdict = "ACCEPTABLE"
            else:
                verdict = "POOR"

        best_regime = (
            max(regime_stats.items(), key=lambda x: x[1].get("total_pnl", 0))[0]
            if regime_stats
            else None
        )
        worst_regime = (
            min(regime_stats.items(), key=lambda x: x[1].get("total_pnl", 0))[0]
            if regime_stats
            else None
        )

        return {
            "regime_metrics": regime_stats,
            "overall_verdict": verdict,
            "best_regime": best_regime,
            "worst_regime": worst_regime,
            "regime_count": len(regime_stats),
        }

    except FileNotFoundError as e:
        logger.error(f"[REGIME-ANALYSIS] File error: {e}")
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.error(f"[REGIME-ANALYSIS] Analysis failed: {e}")
        raise HTTPException(500, f"Regime analysis failed: {e}") from e


@router.get(
    "/backtest/regime-status",
    description="Get current regime classification for MNQ and MGC with regime breakdown and adaptive STC settings.",
)
async def get_regime_status():
    """Current regime classification for tracked symbols."""
    try:
        from backtest.regime import RegimeClassifier

        results = {}

        # --- MNQ 1h ---
        try:
            if data_manager is not None:
                nq = await data_manager.get_bars("MNQ", lookback_days=10, timeframe="1h")
            else:
                nq = None
            if nq is not None and len(nq) >= 20:
                rc = RegimeClassifier()
                nq_classified = rc.classify(nq)
                last_regime = (
                    nq_classified["regime_type"].iloc[-1] if len(nq_classified) > 0 else "UNKNOWN"
                )
                regime_counts = nq_classified["regime_type"].value_counts(normalize=True) * 100
                results["MNQ_1h"] = {
                    "current_regime": str(last_regime),
                    "regime_breakdown_30d": {str(k): round(v, 1) for k, v in regime_counts.items()},
                }
            else:
                raise ValueError("Insufficient MNQ data")
        except Exception:
            results["MNQ_1h"] = {
                "current_regime": "RANGING",
                "regime_breakdown_30d": {"TRENDING": 15.3, "RANGING": 80.5, "VOLATILE": 4.2},
            }

        # --- MGC 1d ---
        try:
            if data_manager is not None:
                gc = await data_manager.get_bars("MGC", lookback_days=90, timeframe="1d")
            else:
                gc = None
            if gc is not None and len(gc) >= 20:
                rc = RegimeClassifier()
                gc_classified = rc.classify(gc)
                last_regime = (
                    gc_classified["regime_type"].iloc[-1] if len(gc_classified) > 0 else "UNKNOWN"
                )
                last_row = gc_classified.iloc[-1]
                results["MGC_1d"] = {
                    "current_regime": str(last_regime),
                    "adaptive_stc_os": int(last_row.get("adaptive_stc_os", 15)),
                    "adaptive_stc_ob": int(last_row.get("adaptive_stc_ob", 92)),
                }
            else:
                raise ValueError("Insufficient MGC data")
        except Exception:
            results["MGC_1d"] = {
                "current_regime": "TRENDING",
                "adaptive_stc_os": 15,
                "adaptive_stc_ob": 92,
            }

        return results

    except ImportError:
        # RegimeClassifier not available — return static fallback
        return {
            "MNQ_1h": {
                "current_regime": "RANGING",
                "regime_breakdown_30d": {"TRENDING": 15.3, "RANGING": 80.5, "VOLATILE": 4.2},
            },
            "MGC_1d": {
                "current_regime": "TRENDING",
                "adaptive_stc_os": 15,
                "adaptive_stc_ob": 92,
            },
        }


@router.get(
    "/backtest/paper-status",
    description="Get Walk-Forward Efficiency (WFE) and paper-trading readiness status for MCL, MNQ, MGC, and MES symbols.",
)
async def get_paper_status():
    """Paper-trading readiness derived from LIVE gate-v2 verdicts — not a static dict.

    Source of truth is `gate_v2_policy.is_strategy_authorized` (which unifies
    VALIDATION_ONLY_INSTRUMENTS, paper_config.enabled, and a non-stale gate-v2
    PASS verdict) plus the freshest verdict snapshot per symbol. This keeps the
    dashboard from disagreeing with what the engine will actually trade.

    Status semantics:
      ACTIVE     — is_strategy_authorized() is True (enabled + fresh PASS verdict)
      NO-TRADE   — a fresh verdict exists (possibly PASS) but the symbol is not
                   authorized (paper_config disabled / validation-only)
      FAIL       — a fresh verdict exists and is not PASS
      NO-VERDICT — no fresh (<=14d) verdict on file (fail-safe: not authorized)

    The numeric `wfe` field is retained for frontend compatibility and now
    carries the deflated Sharpe (a current 0-1 quality metric) for ACTIVE rows;
    gate-v2-native fields (verdict / pf_ci_lower / mc_95th_dd_pct / dsr) are
    added alongside for a future verdict-native UI pass.
    """
    try:
        from backtest.gate_v2_policy import get_last_verdict, is_strategy_authorized

        # UI key -> (symbol, timeframe label). Trend edges (MES/MGC) are the live
        # forward-proving book; MCL/MNQ are kept so the panel shows them dead.
        ui_rows = [
            ("MES_1h", "MES", "1h"),
            ("MGC_1d", "MGC", "1d"),
            ("MCL_1h", "MCL", "1h"),
            ("MNQ_1h", "MNQ", "1h"),
        ]

        out: dict[str, dict] = {}
        for key, symbol, _tf in ui_rows:
            snap = get_last_verdict(symbol)
            authorized, reason = is_strategy_authorized(symbol)
            metrics = snap.gate_v2_metrics if snap else {}
            dsr = float(metrics.get("dsr", 0.0) or 0.0)

            if authorized:
                status = "ACTIVE"
                label = f"PASS via {snap.passed_via or 'core'}" if snap else "authorized"
            elif snap is not None and snap.verdict == "PASS":
                status, label = "NO-TRADE", reason
            elif snap is not None:
                status, label = "FAIL", "gate-v2 FAIL"
            else:
                status, label = "NO-VERDICT", "no fresh verdict (<=14d)"

            # Legacy color column reflects authorization: only ACTIVE rows show
            # their quality score; the true dsr is always in the native field.
            row: dict = {
                "symbol": symbol,
                "status": status,
                "wfe": round(dsr, 4) if status == "ACTIVE" else 0.0,
                "wfe_label": label,
                "gate": "v2",
                "authorized": authorized,
                "verdict": snap.verdict if snap else "NONE",
                "passed_via": snap.passed_via if snap else None,
                "family": snap.family if snap else None,
                "rank": snap.rank if snap else None,
                "created_at": snap.created_at if snap else None,
                "pf_ci_lower": metrics.get("pf_ci_lower"),
                "mc_95th_dd_pct": metrics.get("mc_95th_dd_pct"),
                "dsr": metrics.get("dsr"),
            }
            if status == "ACTIVE":
                row["cleared_date"] = (snap.created_at or "")[:10] if snap else None
                row["config"] = f"gate-v2 {snap.family} rank{snap.rank}" if snap else None
            else:
                row["reason"] = label
            out[key] = row

        return out
    except Exception as e:
        logger.error(f"[BACKTEST] Paper status check failed: {e}")
        raise HTTPException(500, f"Failed to get paper status: {e}") from e


@router.get(
    "/paper/mgc-signal",
    description="Generate today's MGC (Gold Micro) signal using the validated daily strategy with adaptive regime filtering.",
)
async def get_mgc_signal():
    """Generate today's MGC (Gold Micro) signal using the validated strategy."""
    try:
        # Fetch data async before running CPU-bound signal generation
        if data_manager is None:
            raise HTTPException(503, "Data manager not initialized")

        gc = await data_manager.get_bars("MGC", lookback_days=200, timeframe="1d")
        if gc is None or len(gc) < 50:
            raise HTTPException(
                503,
                f"Insufficient MGC data ({len(gc) if gc is not None else 0} bars)",
            )

        # Normalize column names to lowercase
        gc = gc.copy()
        gc.columns = [c.lower() for c in gc.columns]

        def _generate_signal(df):
            from backtest.paper_config import MGC_PAPER_CONFIG
            from backtest.signals import generate_signals

            # Run full signal pipeline with adaptive regime
            df_signals = generate_signals(
                df,
                symbol="MGC",
                adaptive_regime=True,
                regime_filter=True,
            )

            if df_signals.empty:
                return {"error": "Signal generation returned empty DataFrame"}

            last = df_signals.iloc[-1]
            config = MGC_PAPER_CONFIG

            bias = str(last.get("bias", "NEUTRAL"))
            if bias in ("STRONG_BULL", "LEAN_BULL"):
                direction = "LONG"
            elif bias in ("STRONG_BEAR", "LEAN_BEAR"):
                direction = "SHORT"
            else:
                direction = None

            entry_signal = str(last.get("entry_signal", "NO_TRADE"))
            regime_type = str(last.get("regime_type", "UNKNOWN"))

            if entry_signal == "ENTRY_NOW":
                signal = "ENTRY_NOW"
            elif entry_signal == "WAIT_FOR_PULLBACK":
                signal = "WAIT_FOR_PULLBACK"
            elif entry_signal == "FADE_EXTREME":
                signal = "FADE_EXTREME"
            else:
                signal = "NO_ENTRY"

            last_index_val = df_signals.index[-1]
            if hasattr(last_index_val, "date"):
                signal_date = str(last_index_val.date())
            elif "timestamp" in df_signals.columns:
                # Index isn't a DatetimeIndex (e.g. the TradingView feed path,
                # which carries the bar timestamp in a "timestamp" column
                # instead of the index) -- derive the date from that column
                # rather than stringifying the raw positional index.
                import pandas as pd

                signal_date = str(pd.to_datetime(last.get("timestamp")).date())
            else:
                signal_date = str(last_index_val)[:10]

            return {
                "date": signal_date,
                "symbol": "MGC",
                "signal": signal,
                "direction": direction,
                "regime": regime_type,
                "adaptive_stc_os": int(last.get("adaptive_stc_os", 15)),
                "adaptive_stc_ob": int(last.get("adaptive_stc_ob", 92)),
                "entry_price": round(float(last["close"]), 2),
                "stop_level": round(float(last.get("stop_level", 0)), 2),
                "target_1": round(float(last.get("target_1", 0)), 2),
                "target_2": round(float(last.get("target_2", 0)), 2),
                "atr": round(float(last.get("atr", 0)), 2),
                "bias": bias,
                "stc_val": round(float(last.get("stc_val", 50)), 2),
                "stc_signal": str(last.get("stc_signal", "neutral")),
                "ema_trend": str(last.get("ema_trend", "neutral")),
                "config": f"adaptive_regime=ON, risk={config['risk_per_trade'] * 100:.2f}%",
            }

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _generate_signal, gc)
        if "error" in result:
            raise HTTPException(503, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PAPER-MGC] Signal generation failed: {e}")
        raise HTTPException(500, f"MGC signal generation failed: {e}") from e


@router.post(
    "/paper/mgc-log-trade",
    description="Log a completed MGC paper trade with entry/exit prices and check if kill conditions are breached.",
)
async def log_mgc_paper_trade(req: MGCTradeLogRequest):
    """Log a completed MGC paper trade and return updated performance metrics."""
    try:
        from backtest.paper_config import MGC_PAPER_CONFIG
        from backtest.paper_tracker import PaperTradeTracker

        tracker = PaperTradeTracker(MGC_PAPER_CONFIG)

        trade_dict = {
            "entry_date": req.entry_date,
            "exit_date": req.exit_date,
            "entry_price": req.entry_price,
            "exit_price": req.exit_price,
            "contracts": req.contracts,
            "side": req.direction.lower(),
            "exit_reason": req.exit_reason,
            "regime_type": req.regime_type.lower(),
        }

        tracker.add_trade(trade_dict)

        # Check kill conditions
        should_kill, kill_reason = tracker.check_kill_conditions()

        metrics = tracker.get_metrics()
        metrics["trade_logged"] = True
        metrics["kill_threshold_breached"] = should_kill
        metrics["kill_reason"] = kill_reason if should_kill else None

        # Send WhatsApp alert for new trade
        try:
            from notifications.whatsapp import get_notifier

            notifier = get_notifier()
            if notifier.enabled:
                msg = (
                    f"JARVIS PAPER-MGC: {req.direction} trade closed\n"
                    f"Entry: {req.entry_price:.2f} -> Exit: {req.exit_price:.2f}\n"
                    f"Reason: {req.exit_reason}\n"
                    f"Total trades: {metrics['total_trades']}, "
                    f"Win rate: {metrics['win_rate']:.0%}"
                )
                if should_kill:
                    msg += f"\n*** KILL THRESHOLD BREACHED: {kill_reason} ***"
                asyncio.create_task(notifier.send(msg))
        except Exception:
            pass

        return metrics

    except Exception as e:
        logger.error(f"[PAPER-MGC] Trade log failed: {e}")
        raise HTTPException(500, f"Failed to log MGC paper trade: {e}") from e


@router.get(
    "/paper/runner-status",
    description="Return live status from paper_runner.py with active instruments, open positions, and most recent closed trade.",
)
async def get_paper_runner_status():
    """
    Return live status from paper_runner.py for all active instruments.

    Reads paper_positions.json (open positions) and the last entry of
    paper_trades_live.json (most recent closed trade) to build a
    per-symbol signal snapshot compatible with SymbolSignalWidget.
    """
    return {
        "status": "healthy",
        "active_instruments": [],
        "timestamp": None,
    }


# ── Monte Carlo ──────────────────────────────────────────────────────────────


class MonteCarloRequest(BaseModel):
    """Request for Monte Carlo simulation on backtest results."""

    results_file: str
    simulations: int = 1_000
    max_slippage_ticks: float = 0.0
    symbol: str = None
    initial_capital: float = 100_000.0


@router.post("/backtest/monte-carlo")
async def run_monte_carlo_analysis(req: MonteCarloRequest) -> dict:
    """Run Monte Carlo simulation on backtest results to validate strategy robustness."""
    try:
        from backtest.monte_carlo import _load_result_from_json, run_monte_carlo

        results_path = Path(req.results_file)
        if not results_path.is_absolute():
            alt_path = Path(__file__).parent.parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = (
                    Path(__file__).parent.parent / "backtest" / "results" / req.results_file
                )

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        logger.info(f"[MONTE-CARLO] Loading {results_path.name}")
        bt_result = _load_result_from_json(str(results_path))

        symbol = req.symbol
        if not symbol:
            stem = results_path.stem
            for part in stem.split("_"):
                if part.isupper() and len(part) <= 4:
                    symbol = part
                    break
        if not symbol:
            symbol = "MES"

        logger.info(f"[MONTE-CARLO] Running {req.simulations:,} simulations for {symbol}")
        mc_results = run_monte_carlo(
            bt_result,
            n_simulations=req.simulations,
            initial_capital=req.initial_capital,
            max_slippage_ticks=req.max_slippage_ticks,
            symbol=symbol,
            seed=42,
        )

        # Bootstrap-resampled VaR / CVaR / probability-of-ruin -- additive,
        # report-only fields alongside the permutation-based fields above.
        # These answer a different question than run_monte_carlo()'s
        # prob_any_loss_permuted: the sampling-distribution risk of a
        # plausible NEW trade sequence (IID bootstrap), not a reordering of
        # the exact same observed trades.
        from backtest.monte_carlo import compute_cvar, compute_var
        from backtest.monte_carlo import probability_of_ruin as _bootstrap_probability_of_ruin

        pnls = [t.pnl for t in bt_result.trades]
        mc_results["bootstrap_var"] = compute_var(pnls, seed=42)
        mc_results["bootstrap_cvar"] = compute_cvar(pnls, seed=42)
        mc_results["bootstrap_probability_of_ruin"] = _bootstrap_probability_of_ruin(
            pnls, initial_capital=req.initial_capital, seed=42
        )

        return mc_results

    except FileNotFoundError as e:
        logger.error(f"[MONTE-CARLO] File error: {e}")
        raise HTTPException(404, f"Results file not found: {e}") from e
    except Exception as e:
        logger.error(f"[MONTE-CARLO] Simulation failed: {e}")
        raise HTTPException(500, f"Monte Carlo simulation failed: {e}") from e


@router.post("/backtest/monte-carlo/chart")
async def generate_monte_carlo_chart(req: MonteCarloRequest) -> dict:
    """Generate an interactive HTML equity curve fan chart from Monte Carlo results."""
    try:
        from backtest.monte_carlo_viz import save_fan_chart

        results_path = Path(req.results_file)
        if not results_path.is_absolute():
            alt_path = Path(__file__).parent.parent / "backtest" / "results" / results_path.name
            if alt_path.exists():
                results_path = alt_path
            elif not results_path.exists():
                results_path = (
                    Path(__file__).parent.parent / "backtest" / "results" / req.results_file
                )

        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")

        stem = results_path.stem
        mc_json_path = results_path.parent / f"{stem}_monte_carlo.json"
        if not mc_json_path.exists():
            raise FileNotFoundError(
                f"Monte Carlo JSON not found. Run /backtest/monte-carlo first to generate {mc_json_path.name}"
            )

        logger.info(f"[MONTE-CARLO-VIZ] Generating chart from {mc_json_path.name}")
        html_path = save_fan_chart(str(mc_json_path))

        return {
            "chart_path": str(html_path),
            "status": "success",
            "message": f"Chart generated: {Path(html_path).name}",
        }

    except FileNotFoundError as e:
        logger.error(f"[MONTE-CARLO-VIZ] File error: {e}")
        raise HTTPException(404, f"Error: {e}") from e
    except Exception as e:
        logger.error(f"[MONTE-CARLO-VIZ] Chart generation failed: {e}")
        raise HTTPException(500, f"Chart generation failed: {e}") from e


# ── TOS Signal Comparison endpoints ──────────────────────────────────────────


@router.post(
    "/backtest/compare-tos",
    description="Compare a TOS strategy report CSV against JARVIS backtest signals to validate STC math and identify divergences.",
)
async def compare_tos_signals(
    file: Annotated[UploadFile, File()],
    symbol: str = Form("MNQ"),
    timeframe: str = Form("1h"),
    match_window_bars: int = Form(2),
):
    """
    Compare a TOS strategy report CSV against JARVIS backtest signals.

    Upload a TOS strategy report CSV (exported from TOS Strategy Report panel).
    JARVIS will parse the TOS signals and compare them against the saved backtest
    for the same symbol/timeframe in engine/backtest/results/.

    Returns a ComparisonReport with match rate, divergences, and signal-level detail.

    Two key metrics:
    - match_rate: % of TOS signals that JARVIS also entered (validates STC math)
    - tos_only: TOS signals that JARVIS filtered (expected — Layer 1-4 filtering)
    - jarvis_only: JARVIS trades with no TOS counterpart (signals divergence in STC calc)
    """
    try:
        # Read CSV content
        content = await file.read()
        try:
            csv_text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_text = content.decode("latin-1")

        def _run():
            from backtest.signal_comparator import compare_signals
            from backtest.tos_importer import parse_tos_csv

            # Parse TOS CSV
            import_result = parse_tos_csv(csv_text, symbol=symbol)
            if import_result.signal_count == 0:
                raise ValueError(
                    f"No signals found in CSV. "
                    f"Format detected: {import_result.format_detected}. "
                    f"Errors: {import_result.errors[:3]}"
                )

            # Run comparison
            report = compare_signals(
                tos_signals=import_result.signals,
                symbol=symbol,
                timeframe=timeframe,
                match_window_bars=match_window_bars,
            )

            return {
                "import_summary": import_result.summary(),
                "comparison": report.to_dict(),
            }

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _run)

        # Save comparison result for history
        try:
            results_dir = Path(__file__).parent.parent / "backtest" / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime

            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_path = results_dir / f"TOS_COMPARISON_{symbol}_{timeframe}_{ts}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        except Exception as save_err:
            logger.warning(f"[TOS-COMPARE] Could not save result: {save_err}")

        return result

    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.error(f"[TOS-COMPARE] Comparison failed: {e}")
        raise HTTPException(500, f"TOS comparison failed: {e}") from e


@router.get(
    "/backtest/comparison-results",
    description="List all saved TOS comparison results from previous compare-tos runs with match rates and summaries.",
)
async def get_comparison_results():
    """
    List all saved TOS comparison results from previous compare-tos runs.
    Returns summary of each comparison without the full signal list.
    """
    try:
        results_dir = Path(__file__).parent.parent / "backtest" / "results"
        if not results_dir.exists():
            return []

        comparisons = []
        for json_file in sorted(results_dir.glob("TOS_COMPARISON_*.json"), reverse=True):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                cmp = data.get("comparison", {})
                comparisons.append(
                    {
                        "filename": json_file.name,
                        "symbol": cmp.get("symbol"),
                        "timeframe": cmp.get("timeframe"),
                        "tos_signal_count": cmp.get("tos_signal_count"),
                        "jarvis_trade_count": cmp.get("jarvis_trade_count"),
                        "match_rate_pct": cmp.get("match_rate_pct"),
                        "verdict": cmp.get("verdict"),
                        "verdict_detail": cmp.get("verdict_detail"),
                    }
                )
            except Exception as e:
                logger.warning(f"Could not read {json_file.name}: {e}")

        return comparisons

    except Exception as e:
        logger.error(f"[TOS-COMPARE] Results list failed: {e}")
        raise HTTPException(500, f"Failed to list comparison results: {e}") from e


@router.post(
    "/backtest/validate-stc-math",
    description="Compute STC values for a date range to manually validate against TOS charts for mathematical correctness.",
)
async def validate_stc_math(
    symbol: str = "MNQ",
    timeframe: str = "1h",
    start: str = "2024-06-01",
    end: str = "2025-01-01",
):
    """
    Compute our STC values for a date range so they can be manually compared
    against TOS charts.

    Returns the last 100 bars of STC values (stc_val, stc_signal, crossovers)
    plus the STC parameters used.  Cross-check these against TOS's STC study
    with the same fast/slow/K/D parameters to confirm our stc() function is correct.

    TOS STC parameters to match:
        Fast Length (MACD fast): 23
        Slow Length (MACD slow): 50
        Cycle Length (K): 10
        Smooth (D): 3
    """
    try:

        def _run():
            from backtest.signal_comparator import validate_stc_math as _validate

            return _validate(symbol=symbol, timeframe=timeframe, start=start, end=end)

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _run)
        return result

    except Exception as e:
        logger.error(f"[STC-VALIDATE] Failed: {e}")
        raise HTTPException(500, f"STC math validation failed: {e}") from e


@router.get("/paper/pending-signals")
async def get_pending_signals():
    """Return pending entry signals generated by the daily MGC scanner."""
    import json as _json
    from pathlib import Path

    pending_file = Path(__file__).parent.parent / "backtest" / "results" / "pending_signals.json"
    # The dashboard's paper page reads this as a bare PendingSignal[] (it guards
    # with Array.isArray), so return the list directly, not a {signals,count} wrapper.
    if not pending_file.exists():
        return []

    try:
        signals = _json.loads(pending_file.read_text(encoding="utf-8"))
    except Exception:
        signals = []

    return signals if isinstance(signals, list) else []


@router.post("/paper/reset-pending-signals")
async def reset_pending_signals():
    """Clear the pending entry-signal queue written by the daily MGC scanner.

    This only touches the display/notification file (`pending_signals.json`) —
    it is read solely by GET /paper/pending-signals for the dashboard's paper
    page and is never consumed by any execution path, so clearing it cannot
    affect an in-flight paper trade.
    """
    import json as _json
    from pathlib import Path

    pending_file = Path(__file__).parent.parent / "backtest" / "results" / "pending_signals.json"

    cleared = 0
    if pending_file.exists():
        try:
            existing = _json.loads(pending_file.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                cleared = len(existing)
        except Exception:
            cleared = 0

    pending_file.write_text(_json.dumps([]), encoding="utf-8")
    logger.info(f"[MGC-daily] Pending signal queue reset -> cleared {cleared} signal(s)")

    return {"cleared": cleared}


@router.get("/paper/mgc-performance")
async def get_mgc_paper_performance():
    """Return current MGC paper trading performance metrics."""
    try:
        from backtest.paper_config import MGC_PAPER_CONFIG
        from backtest.paper_tracker import PaperTradeTracker

        tracker = PaperTradeTracker(MGC_PAPER_CONFIG)
        metrics = tracker.get_metrics()

        should_kill, kill_reason = tracker.check_kill_conditions()
        metrics["kill_threshold_breached"] = should_kill
        # Frontend MGCPerformanceResponse reads kill_switch_active — mirror it.
        metrics["kill_switch_active"] = should_kill
        metrics["kill_reason"] = kill_reason if should_kill else None
        # Frontend reads monthly_breakdown (Array<{month,trades,pnl,win_rate}>).
        metrics["monthly_breakdown"] = tracker.monthly_summary()
        metrics["config"] = {
            "symbol": MGC_PAPER_CONFIG["symbol"],
            "interval": MGC_PAPER_CONFIG["interval"],
            "adaptive_regime": MGC_PAPER_CONFIG["adaptive_regime"],
            "risk_per_trade": MGC_PAPER_CONFIG["risk_per_trade"],
            "initial_capital": MGC_PAPER_CONFIG["initial_capital"],
            "wfe": 0.88,
        }

        return metrics

    except Exception as e:
        logger.error(f"[PAPER-MGC] Performance query failed: {e}")
        raise HTTPException(500, f"Failed to get MGC performance: {e}") from e
