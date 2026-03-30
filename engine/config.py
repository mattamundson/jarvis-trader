"""
JARVIS TRADER — Configuration
All settings via environment variables (.env file).
Never hardcode secrets.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import sys
import os


def _validate_required_env_vars():
    """
    Startup validation: ensure all required environment variables are set and non-empty.
    Called after TradingConfig initialization to catch missing critical secrets early.
    Fails fast with clear error messages pointing to missing variables.
    """
    required_vars = {
        # API Security
        "API_KEY": "FastAPI X-API-Key header authentication (use strong random value)",

        # Database URLs (critical for operation)
        "POSTGRES_URL": "PostgreSQL connection string (postgresql://user:pass@host:port/db)",
        "REDIS_URL": "Redis connection string (redis://host:port)",

        # Market Data (at least one required)
        "POLYGON_API_KEY": "Polygon.io API key for market data",

        # LLM (Anthropic)
        "ANTHROPIC_API_KEY": "Anthropic API key (sk-ant-api03-...)",
    }

    optional_vars = {
        "FINNHUB_API_KEY": "Alternative market data source",
        "ALPACA_API_KEY": "Alpaca Markets integration",
        "SCHWAB_APP_KEY": "Charles Schwab OAuth (for live trading)",
        "TWILIO_ACCOUNT_SID": "Twilio WhatsApp alerts",
        "TWILIO_AUTH_TOKEN": "Twilio authentication",
        "TWILIO_WHATSAPP_FROM": "Twilio sender number",
        "WHATSAPP_TO": "WhatsApp alert recipient",
    }

    missing_critical = []
    missing_warnings = []

    # Check critical variables
    for var_name, description in required_vars.items():
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing_critical.append((var_name, description))

    # Check optional variables (warn but don't fail)
    for var_name, description in optional_vars.items():
        value = os.environ.get(var_name, "").strip()
        if not value:
            missing_warnings.append((var_name, description))

    # If critical variables missing, fail with detailed error
    if missing_critical:
        error_message = "\n" + "=" * 80 + "\n"
        error_message += "STARTUP ERROR: Missing Required Environment Variables\n"
        error_message += "=" * 80 + "\n\n"

        for var_name, description in missing_critical:
            error_message += f"  {var_name}\n"
            error_message += f"    └─ {description}\n\n"

        error_message += "How to fix:\n"
        error_message += "  1. Copy .env.example to .env:\n"
        error_message += "     cp .env.example .env\n\n"
        error_message += "  2. Edit .env and populate all required variables with real values:\n"
        error_message += "     nano .env\n\n"
        error_message += "  3. NEVER commit .env — it's in .gitignore for your protection\n\n"
        error_message += "  4. Verify .env is loaded:\n"
        error_message += "     source .env && python -c \"import os; print(os.getenv('API_KEY'))\"\n\n"
        error_message += "=" * 80 + "\n"

        print(error_message, file=sys.stderr)
        sys.exit(1)

    # Warn about optional variables
    if missing_warnings:
        print("\n" + "=" * 80, file=sys.stderr)
        print("WARNING: Some optional features will not work without these variables:", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)

        for var_name, description in missing_warnings:
            print(f"  {var_name}", file=sys.stderr)
            print(f"    └─ {description}\n", file=sys.stderr)

        print("These features are optional. If you don't need them, you can ignore this warning.\n", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)


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

    # ── Consecutive Loss Tracking & Position Sizing ──────────────────────
    CONSECUTIVE_LOSS_HALF_SIZE: int = Field(3, description="Losses threshold for 0.5x position size")
    CONSECUTIVE_LOSS_QUARTER_SIZE: int = Field(5, description="Losses threshold for 0.25x position size")
    CONSECUTIVE_LOSS_HALT: int = Field(7, description="Losses threshold for trading halt")
    CONSECUTIVE_LOSS_HALT_HOURS: int = Field(24, description="Duration (hours) of trading halt")

    # ── Autonomy Tier ─────────────────────────────────────────────────────
    LIVE_TRADING_ENABLED: bool = Field(False, description="Set True to enable live trading")
    REQUIRE_HUMAN_APPROVAL: bool = Field(True, description="All live trades require Matt's approval")

    # ── Paper Trading Mode ─────────────────────────────────────────────────
    PAPER_TRADING: bool = Field(True, description="Set False only after 30-day forward test passes. Orders logged but NOT sent to broker when True.")
    PAPER_TRADING_BROKER: str = Field("IB_GATEWAY", description="Broker used for paper trading (IB_GATEWAY for Interactive Brokers Gateway)")

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

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL")

    # ── API Security ──────────────────────────────────────────────────────────
    API_KEY: str = Field("jarvis-dev-key-change-me", env="API_KEY", description="FastAPI X-API-Key header authentication")

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

    def validate_paper_trading_config(self):
        """
        Validate that trading configuration is safe:
        - If PAPER_TRADING=False and SCHWAB_READY=False, raise error
        This prevents accidental live trading without broker ready.
        """
        # Import SCHWAB_READY guard
        try:
            from execution.schwab_connector import SCHWAB_READY
        except ImportError:
            try:
                from engine.execution.schwab_connector import SCHWAB_READY
            except ImportError:
                SCHWAB_READY = False

        if not self.PAPER_TRADING and not SCHWAB_READY:
            raise ValueError(
                "Configuration error: PAPER_TRADING=False requires SCHWAB_READY=True. "
                "Cannot proceed with live trading without a ready broker connector. "
                "Either set PAPER_TRADING=True for paper trading mode, or complete the "
                "Schwab connector implementation and set SCHWAB_READY=True."
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton
settings = TradingConfig()

# Validate all required environment variables on startup
_validate_required_env_vars()

# Validate paper trading config on startup
settings.validate_paper_trading_config()
