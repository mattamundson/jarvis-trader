"""
JARVIS TRADER — Options Analyst Agent (Phase 5)
================================================
Fetches live option chains and identifies high-probability vertical spread
setups based on underlying analysis and IV Rank.
"""

import logging
import os
from typing import Any, Dict, Optional

from analysis.options_signals import OptionsSpreadSignals
from data.options_chain_live import OptionsChainService
from llm.client import JarvisLLMClient
from llm.model_router import MODEL_SONNET, route_task

logger = logging.getLogger("jarvis_trader.agents.options")

class OptionsAnalystAgent:
    def __init__(self, chain_service: Optional[OptionsChainService] = None, llm_client=None):
        self.chain = chain_service
        self.signals = OptionsSpreadSignals()
        self.llm = llm_client or JarvisLLMClient()
        self.model = route_task("default", default_model=MODEL_SONNET)

    async def analyze(self, symbol: str, underlying_bias: str = "NEUTRAL") -> Dict[str, Any]:
        """
        Produce an options analysis report for a symbol.
        """
        if symbol.upper() not in ["SPY", "QQQ", "IWM"]:
            return {"signal": 0.0, "summary": "Options analysis limited to SPY/QQQ/IWM indices."}

        logger.info(f"[OptionsAnalyst] Analyzing {symbol} spreads (Bias: {underlying_bias})...")

        # 1. Fetch Chain
        chain_data = await self.chain.get_chain(symbol)
        if not chain_data:
            return {"signal": 0.0, "summary": "Failed to fetch option chain data."}

        # 2. Generate Candidate Spreads
        spreads = []
        if underlying_bias in ("BULLISH", "STRONG_BULL", "LEAN_BULL"):
            spreads = self.signals.find_bull_put_spreads(chain_data)
        elif underlying_bias in ("BEARISH", "STRONG_BEAR", "LEAN_BEAR"):
            spreads = self.signals.find_bear_call_spreads(chain_data)

        if not spreads:
            return {"signal": 0.0, "summary": f"No valid {underlying_bias} spreads found with target Greeks."}

        best_spread = spreads[0]

        # 3. LLM Final Review (Optional but good for pattern matching)
        # (For now, we'll return the deterministic result)

        return {
            "signal": 1.0 if "BULL" in underlying_bias.upper() else -1.0 if "BEAR" in underlying_bias.upper() else 0.0,
            "best_spread": best_spread,
            "all_candidates_count": len(spreads),
            "summary": f"Identified {best_spread['type']} @ {best_spread['short_strike']}/{best_spread['long_strike']} "
                       f"for {best_spread['net_credit']:.2f} credit. Max risk: {best_spread['max_risk']:.2f}."
        }

def is_options_analyst_enabled() -> bool:
    """Return True if the Phase 5 options analyst is enabled in .env"""
    return os.getenv("ENABLE_OPTIONS_ANALYST", "0").strip() == "1"


_NEUTRAL: Dict[str, Any] = {
    "signal": 0.0,
    "confidence": 0.0,
    "summary": "options analyst disabled",
    "indicators": {"weight": 0.0},
}


class OptionsAnalyst:
    """
    Lightweight, IV-based options signal layer (Phase 5.1).

    Uses three independent sub-signals:
      _skew_signal()  → put/call IV skew
      _term_signal()  → term-structure slope
      _gamma_signal() → gamma exposure estimate

    Each returns (value: float, has_data: bool). Only signals with
    has_data=True contribute to the blended output. When all abstain,
    returns weight=0.0 and signal=0.0. Output is always clamped to [-1, 1].
    """

    def __init__(self) -> None:
        pass

    async def _skew_signal(self, symbol: str, spot_price: Optional[float]) -> tuple:
        return (0.0, False)

    async def _term_signal(self, symbol: str, spot_price: Optional[float]) -> tuple:
        return (0.0, False)

    async def _gamma_signal(self, symbol: str, spot_price: Optional[float]) -> tuple:
        return (0.0, False)

    async def _get_iv_rank(self, symbol: str) -> Optional[float]:
        return None

    async def analyze(self, symbol: str, spot_price: Optional[float] = None) -> Dict[str, Any]:
        if not is_options_analyst_enabled():
            return dict(_NEUTRAL)

        skew, skew_ok = await self._skew_signal(symbol, spot_price)
        term, term_ok = await self._term_signal(symbol, spot_price)
        gamma, gamma_ok = await self._gamma_signal(symbol, spot_price)
        iv_rank = await self._get_iv_rank(symbol)

        active = [(v, ok) for v, ok in [(skew, skew_ok), (term, term_ok), (gamma, gamma_ok)] if ok]
        weight = len(active) / 3.0

        if not active:
            result = {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "options analyst: no_iv_data",
                "indicators": {"weight": 0.0, "reason": "no_iv_data"},
            }
            if iv_rank is not None:
                result["indicators"]["iv_rank"] = iv_rank
            return result

        blended = max(-1.0, min(1.0, sum(v for v, _ in active) / len(active)))
        confidence = weight * abs(blended)
        indicators: Dict[str, Any] = {
            "weight": weight,
            "skew_signal": skew,
            "term_signal": term,
            "gamma_signal": gamma,
        }
        if iv_rank is not None:
            indicators["iv_rank"] = iv_rank

        direction = "bullish" if blended > 0 else "bearish" if blended < 0 else "neutral"
        return {
            "signal": blended,
            "confidence": confidence,
            "summary": f"options analyst: {direction} signal={blended:+.3f}",
            "indicators": indicators,
        }
