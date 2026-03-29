"""
JARVIS TRADER — Backtest Module
Event-driven backtesting with TOS-derived indicators.
"""
try:
    from .backtester import Backtester, BacktestResult, Trade
    from .data_loader import BacktestDataLoader
    from .signals import generate_signals
    from .indicators import wilder_atr, kama, stc, keltner_channels, ema_ribbon

    __all__ = [
        "Backtester", "BacktestResult", "Trade",
        "BacktestDataLoader",
        "generate_signals",
        "wilder_atr", "kama", "stc", "keltner_channels", "ema_ribbon",
    ]
except ImportError:
    # Graceful fallback if dependencies not installed
    __all__ = []
