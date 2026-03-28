"""
JARVIS TRADER — Configuration
All settings via environment variables (.env file).
Never hardcode secrets.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class TradingConfig(BaseSettings):
    """Risk parameters — all configurable, never LLM-modifiable"""

    # ── Risk Controls (Safety Layer) ─────────────────────────────────────
    MAX_POSITION_SIZE_PCT: float = Field(0.05, description="Max 5% of portfolio per position")
    MAX_DAILY_LOSS_PCT: float = Field(0.02, description="Halt trading at -2% daily P&L")
    MAX_DRAWDOWN_PCT: float = Field(0.10, description="Emergency halt at -10% from equity peak")
    MAX_ORDERS_PER_MINUTE: int = Field(10, description="Rate throttle")
    MAX_CORRELATED_EXPOSURE_PCT: float = Field(0.20, description="Max 20% in correlated positions")
    PRICE_COLLAR_PCT: float = Field(0.05, description="Reject orders >5% from NBBO")
    MAX_SINGLE_ORDER_VALUE: float = Field(5000.0, description="No single order > $5,000")
    MAX_MARGIN_UTILIZATION: float = Field(0.40, description="Never exceed 40% of available margin")

    # ── Futures-Specific ─────────────────────────────────────────────────
    MAX_CONTRACTS_PER_INSTRUMENT: int = Field(2, description="Max micro contracts per instrument")
    MAX_OVERNIGHT_CONTRACTS: int = Field(1, description="Max contracts to hold overnight")

    # ── Autonomy Tier ─────────────────────────────────────────────────────
    LIVE_TRADING_ENABLED: bool = Field(False, description="Set True to enable live trading")
    REQUIRE_HUMAN_APPROVAL: bool = Field(True, description="All live trades require Matt's approval")

    # ── Broker: Interactive Brokers ───────────────────────────────────────
    IBKR_HOST: str = Field("127.0.0.1", description="IB Gateway host")
    IBKR_PORT: int = Field(4002, description="4001=live, 4002=paper")
    IBKR_CLIENT_ID: int = Field(1, description="Client ID for IB Gateway connection")
    IBKR_PAPER_MODE: bool = Field(True, description="Always start in paper mode")

    # ── Broker: Charles Schwab ────────────────────────────────────────────
    SCHWAB_APP_KEY: Optional[str] = Field(None, env="SCHWAB_APP_KEY")
    SCHWAB_APP_SECRET: Optional[str] = Field(None, env="SCHWAB_APP_SECRET")
    SCHWAB_CALLBACK_URL: str = Field("https://127.0.0.1", env="SCHWAB_CALLBACK_URL")

    # ── Market Data ───────────────────────────────────────────────────────
    POLYGON_API_KEY: Optional[str] = Field(None, env="POLYGON_API_KEY")
    FINNHUB_API_KEY: Optional[str] = Field(None, env="FINNHUB_API_KEY")
    ALPACA_API_KEY: Optional[str] = Field(None, env="ALPACA_API_KEY")
    ALPACA_SECRET_KEY: Optional[str] = Field(None, env="ALPACA_SECRET_KEY")
    ALPACA_PAPER: bool = Field(True, env="ALPACA_PAPER")

    # ── LLM (Vercel AI Gateway via OIDC) ─────────────────────────────────
    # These are auto-provisioned by `vercel env pull` — no manual API keys needed
    ANTHROPIC_API_KEY: Optional[str] = Field(None, env="ANTHROPIC_API_KEY")  # Fallback if no Gateway
    LLM_PROVIDER: str = Field("anthropic", description="LLM provider")

    # ── Agent Models ──────────────────────────────────────────────────────
    ANALYST_MODEL: str = Field("claude-sonnet-4-6", description="Model for analyst agents")
    TRADER_MODEL: str = Field("claude-opus-4-6", description="Model for trader/risk/fund manager")
    FAST_MODEL: str = Field("claude-haiku-4-5-20251001", description="Model for fast/cheap ops")

    # ── Databases ─────────────────────────────────────────────────────────
    POSTGRES_URL: str = Field("postgresql://jarvis:jarvis@localhost:5432/jarvis_trader")
    REDIS_URL: str = Field("redis://localhost:6379")
    QUESTDB_HOST: str = Field("localhost")
    QUESTDB_PORT: int = Field(9000)

    # ── Notifications (WhatsApp via Twilio) ───────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = Field(None, env="TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(None, env="TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(None, env="TWILIO_WHATSAPP_FROM")
    WHATSAPP_TO: Optional[str] = Field(None, env="WHATSAPP_TO")

    # ── Instruments to Trade ─────────────────────────────────────────────
    FUTURES_WATCHLIST: list[str] = Field(
        default=["MES", "MNQ", "MCL"],
        description="Micro futures contracts to trade"
    )
    OPTIONS_WATCHLIST: list[str] = Field(
        default=["SPY", "QQQ", "AAPL", "TSLA"],
        description="Underlying symbols for options trading"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton
settings = TradingConfig()
