"""
JARVIS TRADER — Configuration
All settings via environment variables (.env file).
Never hardcode secrets.
"""

import os
import sys
from typing import Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_required_env_vars():
    """
    Startup validation: ensure all required environment variables are set and non-empty.
    Called after TradingConfig initialization to catch missing critical secrets early.
    Fails fast with clear error messages pointing to missing variables.

    NOTE: pydantic-settings loads .env into model fields but does NOT write back to
    os.environ. We load dotenv explicitly here so os.environ.get() sees the .env values.
    """
    # Load .env into os.environ so the checks below see file-based values
    try:
        from dotenv import load_dotenv as _load_dotenv

        _load_dotenv(dotenv_path=".env", override=False)
    except ImportError:
        pass  # python-dotenv not installed — fall back to os.environ only

    required_vars = {
        # API Security — must be set to something other than the default stub
        "API_KEY": "FastAPI X-API-Key header authentication (use strong random value)",
    }

    optional_vars = {
        # Databases — engine uses SQLite for paper trading; Postgres/Redis are
        # legacy requirements that are not needed for paper trading mode.
        "POSTGRES_URL": "PostgreSQL connection (only needed for multi-instance deployments)",
        "REDIS_URL": "Redis connection (only needed for caching/rate-limiting at scale)",
        # Market Data
        "POLYGON_API_KEY": "Polygon.io API key for market data (Tier 2 after IBKR)",
        # LLM pipeline — engine runs signal generation without Anthropic key;
        # LLM agents are skipped if this is absent.
        "ANTHROPIC_API_KEY": "Anthropic API key (sk-ant-api03-...) — enables LLM agent pipeline",
        # Other market data sources
        "FINNHUB_API_KEY": "Alternative market data source",
        "ALPACA_API_KEY": "Alpaca Markets integration",
        "SCHWAB_APP_KEY": "Charles Schwab OAuth (for live trading)",
        "TWILIO_ACCOUNT_SID": "Twilio WhatsApp alerts",
        "TWILIO_AUTH_TOKEN": "Twilio authentication",
        "TWILIO_WHATSAPP_FROM": "Twilio sender number",
        "WHATSAPP_TO": "WhatsApp alert recipient",
        "DASHBOARD_PUBLIC_URL": "Dashboard URL for approval links in outbound alerts (default localhost:3010)",
        "JARVIS_DISCORD_APPROVAL_WEBHOOK": "Optional Discord incoming webhook URL for pending-approval notifications",
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
        error_message += (
            "     source .env && python -c \"import os; print(os.getenv('API_KEY'))\"\n\n"
        )
        error_message += "=" * 80 + "\n"

        print(error_message, file=sys.stderr)
        sys.exit(1)

    # Warn about optional variables
    if missing_warnings:
        print("\n" + "=" * 80, file=sys.stderr)
        print(
            "WARNING: Some optional features will not work without these variables:",
            file=sys.stderr,
        )
        print("=" * 80 + "\n", file=sys.stderr)

        for var_name, description in missing_warnings:
            print(f"  {var_name}", file=sys.stderr)
            print(f"    └─ {description}\n", file=sys.stderr)

        print(
            "These features are optional. If you don't need them, you can ignore this warning.\n",
            file=sys.stderr,
        )
        print("=" * 80 + "\n", file=sys.stderr)


class TradingConfig(BaseSettings):
    """Risk parameters — all configurable, never LLM-modifiable"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

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
    CONSECUTIVE_LOSS_HALF_SIZE: int = Field(
        3, description="Losses threshold for 0.5x position size"
    )
    CONSECUTIVE_LOSS_QUARTER_SIZE: int = Field(
        5, description="Losses threshold for 0.25x position size"
    )
    CONSECUTIVE_LOSS_HALT: int = Field(7, description="Losses threshold for trading halt")
    CONSECUTIVE_LOSS_HALT_HOURS: int = Field(24, description="Duration (hours) of trading halt")

    # ── Trade Management Rules ─────────────────────────────────────────
    REENTRY_LOCKOUT_MINUTES: int = 240  # 4-hour lockout after stop-out
    BREAKEVEN_STOP_ATR_MULT: float = 0.50  # Move stop to BE after +0.50x ATR gain
    SESSION_FLATTEN_TIME_ET: str = "15:45"  # Flatten all positions at 3:45 PM ET
    MCL_INVENTORY_BLACKOUT_MINUTES: int = (
        45  # EIA blackout: 15min before + 30min after Wed 10:30 ET
    )

    # ── Infrastructure ────────────────────────────────────────────────────
    SQLITE_DB_PATH: str = Field(
        "data/jarvis_trader.db",
        description="Canonical SQLite database path (relative to engine root)",
    )

    # ── STC Mid-Range Pre-Filter ──────────────────────────────────────────
    # When enabled, skips the full LLM pipeline if STC is between LOW and HIGH.
    # Default LOW=15/HIGH=83 (the OS/OB thresholds) means only extreme readings
    # get fast-pathed; all mid-range values proceed to full LLM analysis.
    STC_MIDRANGE_SKIP_ENABLED: bool = Field(
        True, description="Enable STC mid-range pre-filter to reduce LLM cost"
    )
    STC_MIDRANGE_SKIP_LOW: float = Field(
        15.0, description="STC below this value bypasses pipeline (set to OS threshold)"
    )
    STC_MIDRANGE_SKIP_HIGH: float = Field(
        83.0, description="STC above this value bypasses pipeline (set to OB threshold)"
    )

    # ── STC Signal Thresholds (Schaff Trend Cycle) ────────────────────────
    # Canonical OS/OB levels used by the pre-filter and signal generators.
    STC_OVERSOLD: float = Field(
        15.0, description="STC below this = oversold / potential long setup"
    )
    STC_OVERBOUGHT: float = Field(
        83.0, description="STC above this = overbought / potential short setup"
    )
    STC_REQUIRED: bool = Field(
        True, description="Require STC signal alignment before pipeline generates a directional signal"
    )

    # ── Futures-Specific Confidence Tuning ───────────────────────────────
    # Futures (MCL, MNQ, MES) have cleaner, faster technical signals than equities.
    # Lower min-confidence threshold and apply a small boost after aggregation.
    FUTURES_CONFIDENCE_BOOST: float = Field(
        0.05,
        description="Additive boost applied to raw confidence for futures instruments "
                    "(compensates for fewer available analyst inputs vs. equities)",
    )
    FUTURES_MIN_CONFIDENCE_TO_TRADE: float = Field(
        0.55,
        description="Minimum pipeline confidence required before a futures BUY/SELL is issued "
                    "(lower than equity threshold because futures signals are more direct)",
    )
    EQUITY_MIN_CONFIDENCE_TO_TRADE: float = Field(
        0.62,
        description="Minimum pipeline confidence required before an equity BUY/SELL is issued",
    )

    # ── Autonomy Tier ─────────────────────────────────────────────────────
    LIVE_TRADING_ENABLED: bool = Field(False, description="Set True to enable live trading")
    REQUIRE_HUMAN_APPROVAL: bool = Field(
        True, description="All live trades require Matt's approval"
    )

    ALLOW_PAPER_SIMULATED_ORDERS: bool = Field(
        False,
        description="When True, paper trading mode allows simulated orders via check_order route",
    )

    # ── Capital ────────────────────────────────────────────────────────────
    INITIAL_CAPITAL: float = Field(
        10000.0,
        description="Starting paper account balance in USD. Used by PnLMonitor when no broker equity is available.",
    )

    DASHBOARD_PUBLIC_URL: str = Field(
        default="http://localhost:3010",
        description="Public dashboard base URL for links in WhatsApp / Discord approval alerts.",
    )

    # ── Paper Trading Mode ─────────────────────────────────────────────────
    PAPER_TRADING: bool = Field(
        True,
        description="Set False only after 30-day forward test passes. Orders logged but NOT sent to broker when True.",
    )
    PAPER_TRADING_BROKER: str = Field(
        "IB_GATEWAY",
        description="Broker used for paper trading (IB_GATEWAY for Interactive Brokers Gateway)",
    )

    # ── Broker: Interactive Brokers ───────────────────────────────────────
    IBKR_HOST: str = Field("127.0.0.1", description="IB Gateway host")
    IBKR_PORT: int = Field(4002, description="4001=live, 4002=paper")
    IBKR_CLIENT_ID: int = Field(1, description="Client ID for IB Gateway connection")
    IBKR_PAPER_MODE: bool = Field(True, description="Always start in paper mode")

    # ── Broker: Charles Schwab ────────────────────────────────────────────
    SCHWAB_APP_KEY: Optional[str] = Field(default=None, description="Charles Schwab app key")
    SCHWAB_APP_SECRET: Optional[str] = Field(default=None, description="Charles Schwab app secret")
    SCHWAB_CALLBACK_URL: str = Field(
        "https://127.0.0.1", description="Charles Schwab OAuth callback URL"
    )
    SCHWAB_READY: bool = Field(
        default=False,
        description="Enable Schwab connector (requires SCHWAB_APP_KEY and SCHWAB_APP_SECRET)",
    )

    # ── Market Data ───────────────────────────────────────────────────────
    POLYGON_API_KEY: Optional[str] = Field(default=None, description="Polygon.io API key")
    FRED_API_KEY: Optional[str] = Field(default=None, description="Federal Reserve FRED API key")
    FINNHUB_API_KEY: Optional[str] = Field(default=None, description="Finnhub API key")
    BRAVE_API_KEY: Optional[str] = Field(default=None, description="Brave Search API key for news analyst live web search")
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca Markets API key")
    ALPACA_SECRET_KEY: Optional[str] = Field(default=None, description="Alpaca Markets secret key")
    ALPACA_PAPER: bool = Field(default=True, description="Use Alpaca paper trading")

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(
        "INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )

    # ── API Security ──────────────────────────────────────────────────────────
    API_KEY: Optional[str] = Field(
        default=None,
        description="FastAPI X-API-Key header authentication (must be set explicitly in .env)",
    )

    # ── LLM (Vercel AI Gateway via OIDC) ─────────────────────────────────
    # These are auto-provisioned by `vercel env pull` — no manual API keys needed
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None, description="Anthropic API key for LLM agent pipeline"
    )
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
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None, description="Twilio account SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None, description="Twilio auth token")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(default=None, description="Twilio WhatsApp sender")
    WHATSAPP_TO: Optional[str] = Field(default=None, description="WhatsApp recipient number")

    # ── Instruments to Trade ─────────────────────────────────────────────
    FUTURES_WATCHLIST: Union[str, list[str]] = Field(
        default="MCL,MNQ,MES",
        description="Micro futures contracts to trade (comma-separated or list). "
        "MCL first (WFE=0.82), MNQ second (WFE=0.57). MES last (WFE=0.09, data-collection only). "
        "[:2] slice used by watchlist scheduler must yield MCL+MNQ.",
    )
    # Options module: dry-run in paper before enabling live routing; see docs/backlog/EPICS_12_17_FOLLOWONS.md
    OPTIONS_WATCHLIST: Union[str, list[str]] = Field(
        default=["SPY", "QQQ", "AAPL", "TSLA"], description="Underlying symbols for options trading"
    )

    @field_validator("FUTURES_WATCHLIST", "OPTIONS_WATCHLIST", mode="before")
    @classmethod
    def parse_watchlist(cls, v):
        """
        Parse list fields from comma-separated string or JSON array.
        Supports both formats:
        - Comma-separated: "MCL,MNQ"
        - JSON array: ["MCL", "MNQ"]
        Returns: list[str]
        """
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                try:
                    return json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    pass
            return [item.strip().strip("\"'") for item in v.split(",") if item.strip()]
        return v

    @field_validator("API_KEY", mode="after")
    @classmethod
    def validate_api_key_not_default(cls, v):
        """
        Fail fast if API_KEY is not explicitly set.
        Raises an error if API_KEY is None or a known placeholder value.
        """
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise ValueError(
                "API_KEY must be explicitly set to a real value. "
                "Edit .env and set API_KEY to a strong random string. "
                "Example: API_KEY=your-secret-api-key-here"
            )
        if v == "CHANGE_ME_BEFORE_DEPLOY":
            raise ValueError(
                "API_KEY must be explicitly set to a real value. "
                "Found placeholder: 'CHANGE_ME_BEFORE_DEPLOY'. "
                "Edit .env and set API_KEY to a strong random string."
            )
        return v


# ── Module-level singleton ─────────────────────────────────────────
settings = TradingConfig()

# Validate required environment variables on module load
_validate_required_env_vars()
