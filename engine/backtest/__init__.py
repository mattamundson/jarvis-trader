"""
JARVIS TRADER — Backtest Module
Event-driven backtesting with TOS-derived indicators.
"""

try:
    # trade_manager and metrics are the canonical sources; backtester re-exports them
    from .backtester import Backtester, BacktestResult, Trade
    from .data_loader import BacktestDataLoader
    from .indicators import ema_ribbon, kama, keltner_channels, stc, wilder_atr
    from .signals import generate_signals

    __all__ = [
        "Backtester",
        "BacktestResult",
        "Trade",
        "BacktestDataLoader",
        "generate_signals",
        "wilder_atr",
        "kama",
        "stc",
        "keltner_channels",
        "ema_ribbon",
    ]
except ImportError:
    # Graceful fallback if dependencies not installed
    __all__ = []
