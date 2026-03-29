"""
JARVIS TRADER — Agents package
================================
Exports all trading analysis agents, debate infrastructure,
and the three senior decision-making agents plus the pipeline orchestrator.
"""
from .technical_analyst import TechnicalAnalystAgent, TechnicalReport
from .bull_researcher import BullResearcherAgent, BullReport
from .bear_researcher import BearResearcherAgent, BearReport
from .debate import DebateOrchestrator, DebateResult
from .news_analyst import NewsAnalystAgent, NewsReport
from .social_analyst import SocialAnalystAgent, SocialReport
from .fundamental_analyst import FundamentalistAgent, FundamentalReport
from .trader import TraderAgent, TradeDecision
from .risk_manager import RiskManagerAgent, RiskDecision
from .fund_manager import FundManagerAgent, FundDecision
from .pipeline import TradingPipeline
from .thinkscript_generator import ThinkScriptGeneratorAgent, ThinkScriptResult
from .schemas import (
    Action, OrderType, MarketRegime, TrendDirection, EntrySignal,
    ATRLevels, IBLevels, TPOData, KeltnerBands, MomentumSignals,
    ResearchCase, pipeline_summary,
)

__all__ = [
    # Technical analysis
    "TechnicalAnalystAgent",
    "TechnicalReport",
    # Debate agents
    "BullResearcherAgent",
    "BullReport",
    "BearResearcherAgent",
    "BearReport",
    # Debate orchestration
    "DebateOrchestrator",
    "DebateResult",
    # News, social, and fundamental analysis
    "NewsAnalystAgent",
    "NewsReport",
    "SocialAnalystAgent",
    "SocialReport",
    "FundamentalistAgent",
    "FundamentalReport",
    # Senior decision-making agents
    "TraderAgent",
    "TradeDecision",
    "RiskManagerAgent",
    "RiskDecision",
    "FundManagerAgent",
    "FundDecision",
    # Pipeline orchestrator
    "TradingPipeline",
    # ThinkScript generation
    "ThinkScriptGeneratorAgent",
    "ThinkScriptResult",
    # Typed schemas (enums + dataclasses + helpers)
    "Action", "OrderType", "MarketRegime", "TrendDirection", "EntrySignal",
    "ATRLevels", "IBLevels", "TPOData", "KeltnerBands", "MomentumSignals",
    "ResearchCase", "pipeline_summary",
]
