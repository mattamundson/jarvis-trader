"""
JARVIS TRADER -- Postgres SQLAlchemy Models
============================================
Defines the native Database schemas matching the SQLite architecture
for the Alembic async migration pipeline.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass

class PaperTrade(Base):
    """Corresponds to paper_trades table"""
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), index=True)
    size: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Executions
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Metadata
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    regime: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bias: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class PipelineRun(Base):
    """Corresponds to alert_log and pipeline_runs tracking LLM iterations"""
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True) # UUID string
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    duration_ms: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50)) # e.g. 'market_open_15m'

    l1_regime: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    l2_structure: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    l3_bias: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    final_action: Mapped[str] = mapped_column(String(20)) # LONG/SHORT/HOLD

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class LLMCostRecord(Base):
    """Tracks token spend per agent across Anthropic/OpenAI"""
    __tablename__ = "llm_costs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(100))

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)

class SafetyAlert(Base):
    """Logs kill-switch activations, drawdown breaches, and tilt alerts"""
    __tablename__ = "safety_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    alert_type: Mapped[str] = mapped_column(String(50), index=True) # e.g. TILT_DETECTED, DRAWDOWN_LIMIT
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
