from typing import Optional

from pydantic import BaseModel


class BotSignal(BaseModel):
    """Parsed signal from proton-bot-alerts or instrument channels (es, nq, gc, cl, ym, rty, eurusd, btc, spy)."""

    message_id: str
    timestamp: str  # ISO 8601 UTC
    symbol: str  # e.g. "ES", "NQ", "GC", "CL"
    timeframe: Optional[str] = None  # e.g. "1 m", "15 m"
    direction: Optional[str] = None  # "LONG" or "SHORT"
    signal_type: Optional[str] = None  # "ENTRY" or "EXIT"
    entry_price: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    stop1: Optional[float] = None
    stop2: Optional[float] = None
    win_rate: Optional[float] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    rr: Optional[float] = None
    gain: Optional[float] = None
    draw: Optional[float] = None
    net: Optional[float] = None
    last_price: Optional[float] = None
    raw_description: Optional[str] = None
    source_channel: Optional[str] = None


class IBReport(BaseModel):
    """Initial Balance report from indicator-alerts channel."""

    message_id: str
    timestamp: str  # ISO 8601 UTC
    symbol: str  # e.g. "ES", "NQ"
    timeframe: Optional[str] = None
    ib_open: Optional[float] = None
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    ib_close: Optional[float] = None
    ib_range: Optional[float] = None
    ibu50: Optional[float] = None
    ibu100: Optional[float] = None
    ibd50: Optional[float] = None
    ibd100: Optional[float] = None
    auction_context: Optional[str] = None
    trade_plan: Optional[str] = None
    raw_content: Optional[str] = None
    source_channel: str = "indicator-alerts"


class CoreyAlert(BaseModel):
    """Manual trade alert from Corey (tathedog) in trade-alerts channel."""

    message_id: str
    timestamp: str  # ISO 8601 UTC
    content: str
    symbol: Optional[str] = None
    direction: Optional[str] = None  # "LONG" or "SHORT"
    price: Optional[float] = None
    source_channel: str = "trade-alerts"


class CoreyCommentary(BaseModel):
    """Market commentary from Corey (tathedog) in market-updates or general channels."""

    message_id: str
    timestamp: str  # ISO 8601 UTC
    content: str
    channel: str  # "market-updates" or "general"
    author_id: str = "564449478174703646"
