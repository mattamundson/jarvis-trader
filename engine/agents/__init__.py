"""
JARVIS TRADER — Agents package
================================
Exports all trading analysis agents, debate infrastructure,
and the three senior decision-making agents plus the pipeline orchestrator.
"""
from .bear_researcher import BearReport, BearResearcherAgent
from .bull_researcher import BullReport, BullResearcherAgent
from .debate import DebateOrchestrator, DebateResult
from .fund_manager import FundDecision, FundManagerAgent
from .fundamental_analyst import FundamentalistAgent, FundamentalReport
from .news_analyst import NewsAnalystAgent, NewsReport
from .pipeline import TradingPipeline
from .risk_manager import RiskDecision, RiskManagerAgent
from .schemas import (
    Action,
    ATRLevels,
    EntrySignal,
    IBLevels,
    KeltnerBands,
    MarketRegime,
    MomentumSignals,
    OrderType,
    ResearchCase,
    TPOData,
    TrendDirection,
    pipeline_summary,
)
from .social_analyst import SocialAnalystAgent, SocialReport
from .technical_analyst import TechnicalAnalystAgent, TechnicalReport
from .thinkscript_generator import ThinkScriptGeneratorAgent, ThinkScriptResult
from .trader import TradeDecision, TraderAgent

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
