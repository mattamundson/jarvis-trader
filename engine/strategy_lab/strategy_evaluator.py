"""
Runs a backtest for a strategy variant and applies dual-gate validation.

Uses the optimizer's _compute_signals function (which handles atr_stop_mult /
atr_target_mult) rather than the standard generate_signals path, exactly
matching how grid-search and Bayesian optimisation work internally.
"""
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Dual-gate thresholds (autotrade pattern)
RISK_MAX_DRAWDOWN_PCT = 15.0    # Risk gate: max allowed drawdown
PROFIT_MIN_SHARPE = 1.2         # Profit gate: minimum Sharpe ratio
PROFIT_MIN_CALMAR = 0.8         # Profit gate: minimum Calmar ratio
PROFIT_MIN_PF = 1.8             # Profit gate: minimum profit factor
PROFIT_MIN_TRADES = 20          # Profit gate: minimum trade count
PROFIT_MIN_EXPOSURE_PCT = 25.0  # Profit gate: minimum market exposure


def validate_backtest_stats(stats: dict) -> dict:
    """
    Apply dual-gate validation to backtest statistics.

    Returns:
        {verdict, risk_passed, profit_passed, violations: list[str]}
    """
    n_trades = stats.get('n_trades', stats.get('total_trades', 0))
    pf = stats.get('profit_factor', stats.get('pf', None))

    if n_trades == 0 or pf is None:
        return {
            'verdict': 'INVALID',
            'risk_passed': False,
            'profit_passed': False,
            'violations': ['Zero trades or null profit factor'],
        }

    # RISK GATE
    risk_violations = []
    max_dd = abs(stats.get('max_drawdown_pct', stats.get('max_drawdown', 0)))
    if max_dd > RISK_MAX_DRAWDOWN_PCT:
        risk_violations.append(f"Max DD {max_dd:.1f}% > {RISK_MAX_DRAWDOWN_PCT}% limit")
    risk_passed = len(risk_violations) == 0

    # PROFIT GATE
    profit_violations = []
    if n_trades < PROFIT_MIN_TRADES:
        profit_violations.append(f"Trades: {n_trades} < {PROFIT_MIN_TRADES} minimum")

    exposure = stats.get('exposure_time_pct', 100.0)  # Default 100% if not tracked
    if exposure < PROFIT_MIN_EXPOSURE_PCT:
        profit_violations.append(f"Exposure: {exposure:.1f}% < {PROFIT_MIN_EXPOSURE_PCT}%")

    sharpe = stats.get('sharpe', stats.get('sharpe_ratio', 0))
    if sharpe < PROFIT_MIN_SHARPE:
        profit_violations.append(f"Sharpe: {sharpe:.2f} < {PROFIT_MIN_SHARPE}")

    calmar = stats.get('calmar_ratio', 0)
    if calmar < PROFIT_MIN_CALMAR:
        profit_violations.append(f"Calmar: {calmar:.2f} < {PROFIT_MIN_CALMAR}")

    if pf < PROFIT_MIN_PF:
        profit_violations.append(f"PF: {pf:.2f} < {PROFIT_MIN_PF}")

    profit_passed = len(profit_violations) == 0
    all_violations = risk_violations + profit_violations

    if not risk_passed:
        verdict = 'DISCARD_RISK'
    elif not profit_passed:
        verdict = 'DISCARD_PROFIT'
    else:
        verdict = 'ELIGIBLE'

    return {
        'verdict': verdict,
        'risk_passed': risk_passed,
        'profit_passed': profit_passed,
        'violations': all_violations,
    }


def evaluate_strategy_variant(
    params: dict,
    symbol: str = "MES",
    start: str = "2024-06-01",
    end: str = "2026-03-27",
) -> dict:
    """
    Run a backtest for the given parameters and return verdict.

    Uses optimizer._compute_signals (handles atr_stop_mult / atr_target_mult)
    then Backtester.run() — same path as grid-search.

    Returns:
        Dict with verdict, risk_passed, profit_passed, violations, metrics, parameters
    """
    try:
        # Ensure engine root is on sys.path so sibling packages import cleanly
        engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if engine_root not in sys.path:
            sys.path.insert(0, engine_root)

        from backtest.backtester import Backtester
        from backtest.data_loader import BacktestDataLoader
        from backtest.optimizer import _compute_signals  # noqa: PLC2701

        interval = params.get('timeframe', '1h')

        loader = BacktestDataLoader()
        df = loader.load(symbol=symbol, start=start, end=end, interval=interval)

        if df is None or df.empty or len(df) < 100:
            bar_count = len(df) if df is not None else 0
            return {
                'parameters': params,
                'verdict': 'INVALID',
                'risk_passed': False,
                'profit_passed': False,
                'violations': [f'Insufficient data: {bar_count} bars'],
                'metrics': {},
            }

        # Recompute signals with variant STC + ATR parameters
        df_signals = _compute_signals(
            df,
            stc_oversold=float(params.get('stc_oversold', 15)),
            stc_overbought=float(params.get('stc_overbought', 83)),
            atr_stop_mult=float(params.get('atr_stop_mult', 0.70)),
            atr_target_mult=float(params.get('atr_target_mult', 1.50)),
            regime_filter=bool(params.get('regime_filter', True)),
        )

        multiplier = loader.get_multiplier(symbol)
        backtester = Backtester()
        result = backtester.run(df_signals, symbol=symbol, multiplier=multiplier)

        # Normalise to dict
        if hasattr(result, 'to_dict'):
            stats = result.to_dict()
        elif isinstance(result, dict):
            stats = result
        else:
            stats = vars(result)

    except Exception as e:
        logger.warning("Backtest failed for params %s: %s", params, e, exc_info=True)
        return {
            'parameters': params,
            'verdict': 'INVALID',
            'risk_passed': False,
            'profit_passed': False,
            'violations': [f'Backtest error: {str(e)[:120]}'],
            'metrics': {},
        }

    validation = validate_backtest_stats(stats)

    return {
        'parameters': params,
        **validation,
        'metrics': stats,
    }
