"""
JARVIS TRADER — Options Analyst Agent (Phase 5)
================================================
Fetches live option chains and identifies high-probability vertical spread
setups based on underlying analysis and IV Rank.
"""

import logging
import os
from typing import Dict, Any, Optional

from data.options_chain_live import OptionsChainService
from analysis.options_signals import OptionsSpreadSignals
from llm.model_router import route_task, MODEL_SONNET
from llm.client import JarvisLLMClient

logger = logging.getLogger("jarvis_trader.agents.options")

class OptionsAnalystAgent:
    def __init__(self, chain_service: OptionsChainService, llm_client=None):
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

# Legacy alias for backward compatibility
OptionsAnalyst = OptionsAnalystAgent
