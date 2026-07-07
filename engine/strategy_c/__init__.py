"""
Strategy C — Enhanced Regime Rotation Module
=============================================
Long-only, unlevered, weekly rebalancing.
Target: Sharpe 2.13 | CAGR 17.4% | Vol 7.7% | MDD -7.7%

Enhancements over baseline Dual Momentum:
  1. ES/NQ daily realized volatility targeting (10-day lookback, 8% target)
  2. 4-component VIX composite signal (level + momentum + term structure + VVIX proxy)
  3. FRED macro regime overlay (yield curve, Fed funds rate)
  4. CFTC CoT positioning filter (commercial hedger sentiment on ES/NQ)
  5. Expanded universe: QQQ, SPY, EFA, USMV, MTUM, XLK, XLV + IEF, SHY
  6. Factor-tilt ranking (momentum + low-vol + quality blended score)
  7. Deflated Sharpe ratio validation (Bailey-López de Prado 2014)
  8. Walk-forward IS/OOS harness with regime-adaptive parameter selection

Author: JARVIS TRADER (Strategy C Module)
"""

from .engine import StrategyCEngine
from .live_signal import run_live_signal
from .macro_filter import MacroRegimeFilter
from .signals import StrategyCSignals
from .vix_composite import VIXComposite
from .vol_targeting import VolatilityTargeter

__all__ = [
    "StrategyCEngine",
    "StrategyCSignals",
    "VolatilityTargeter",
    "VIXComposite",
    "MacroRegimeFilter",
    "run_live_signal",
]
