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
    # Use override=True to ensure .env values take precedence over system env vars (e.g., ANTHROPIC_API_KEY=test from system)
<<<<<<< HEAD
    try:
        from dotenv import load_dotenv as _load_dotenv

        _load_dotenv(dotenv_path=".env", override=True)
    except ImportError:
        pass  # python-dotenv not installed — fall back to os.environ only
=======
    #
    # Skip entirely under pytest (TESTING=1, set by tests/conftest.py before
    # config is ever imported): loading the LIVE .env here would clobber
    # conftest's safe test stubs and, for provider keys conftest doesn't
    # stub (MOONSHOT_API_KEY, JARVIS_DECISION_PRIMARY, GOOGLE_API_KEY, ...),
    # inject real credentials into a test process — llm/client.py reads
    # those straight from os.environ, so a leaked key means a test can make
    # a real, billed network call to an LLM provider instead of the
    # deterministic mocked/unconfigured path it's asserting on.
    if os.environ.get("TESTING") != "1":
        try:
            from dotenv import load_dotenv as _load_dotenv

            _load_dotenv(dotenv_path=".env", override=True)
        except ImportError:
            pass  # python-dotenv not installed — fall back to os.environ only
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

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
    MAX_POSITION_SIZE_PCT: float = Field(
        0.10,
        description="Max 10% of portfolio per position (reconciled to .env live truth 2026-06-25)",
    )
    MAX_DAILY_LOSS_PCT: float = Field(
        0.06, description="Halt trading at -6% daily P&L ($10K aggressive profile, 2026-06-25)"
    )
    MAX_DAILY_LOSS_USD: float = Field(100.0, description="Halt trading at flat $100 daily P&L")
    MAX_TRADE_LOSS_USD: float = Field(50.0, description="Max loss per single trade ticket is $50")
    MAX_DRAWDOWN_PCT: float = Field(
        0.20,
        description="Emergency halt at drawdown from equity peak. Reconciled to .env live truth 0.20 (-20%) on 2026-06-25 ($10K aggressive profile). engine/.env remains the source of truth for the live value.",
    )
    MAX_ORDERS_PER_MINUTE: int = Field(10, description="Rate throttle")
    MAX_CORRELATED_EXPOSURE_PCT: float = Field(
        0.50,
        description="Max 50% in correlated positions (reconciled to .env live truth 2026-06-25)",
    )
    PRICE_COLLAR_PCT: float = Field(0.05, description="Reject orders >5% from NBBO")
    MAX_SINGLE_ORDER_VALUE: float = Field(
        100000.0,
        description="No single order > $100,000 notional (reconciled to .env live truth 2026-06-25; futures notional is large)",
    )
    MAX_MARGIN_UTILIZATION: float = Field(0.40, description="Never exceed 40% of available margin")

    # ── Futures-Specific ─────────────────────────────────────────────────
    # MAX_CONTRACTS_PER_INSTRUMENT hard cap is 20 (Phase 3 authorization).
    # Originally capped at 2 (2026-04-10 safety incident: runaway scanner
    # created 3-contract MES shorts on stale price data), raised to 20 for
    # multi-contract live trading expansion.
    MAX_CONTRACTS_PER_INSTRUMENT: int = Field(
        2,
        description="Max micro contracts per instrument (Phase 3: up to 20 authorized)",
    )
    MAX_OVERNIGHT_CONTRACTS: int = Field(1, description="Max contracts to hold overnight")

    # ── Correlation-Aware Sizing ─────────────────────────────────────────
    INSTRUMENT_CORRELATION_PAIRS: dict = Field(
        default={"MNQ-MES": 0.95, "MCL-MNQ": 0.10, "MCL-MES": 0.10},
        description="Instrument pair correlation values for sizing reduction",
    )
    CORRELATION_THRESHOLD: float = Field(
        0.80,
        description="Correlation >= threshold triggers correlated pair sizing rule",
    )
    CORRELATED_PAIR_MAX_CONTRACTS: int = Field(
        1,
        description="Reduced max contracts when both instruments in a correlated pair are open",
    )

    # ── Volatility-Targeting Sizing (default OFF; OOS-validated on MGC) ───
    # Scales contracts toward a constant target volatility: a final risk
    # overlay applied after VIX scaling. w = clip(target_vol / realized_vol,
    # 0, max_leverage). DEFAULT OFF — inert until explicitly enabled.
    # Evidence: backtest/vol_target_wfo.py — MGC trend OOS Sharpe +0.69,
    # MaxDD -59% (ROBUST_OOS, 6/10 windows); realized vol read from the live
    # technical indicator rv_20_ann_pct (same 20-bar annualized formula).
    VOL_TARGET_ENABLED: bool = Field(
        False,
        description="Enable volatility-targeting position-size overlay (default OFF)",
    )
    VOL_TARGET_MAX_LEVERAGE: float = Field(
        3.0,
        description="Max vol-target up-scaling multiplier (clip ceiling for target/realized vol)",
    )
    VOL_TARGET_PER_SYMBOL: dict = Field(
        default={"MGC": 13.3},
        description="Per-symbol target annualized realized vol (%) for vol-targeting sizing "
        "(MGC=13.3 calibrated from the WFO study global target_vol)",
    )

    # Correlation-aware portfolio sizing overlay (P2.3, DEFAULT OFF). Trims a new
    # position when it would stack correlated risk on the existing open book
    # ("size MES down when MGC is already hot"). Inert until enabled AND validated.
    CORRELATION_SIZING_ENABLED: bool = Field(
        False,
        description="Enable correlation-aware portfolio-sizing overlay (default OFF)",
    )
    CORRELATION_MAX_PORTFOLIO_RISK_USD: float = Field(
        200.0,
        description="Aggregate correlated-risk ceiling ($) the new position is trimmed to fit",
    )
    CORRELATION_DEFAULT_CORR: float = Field(
        0.5,
        description="Correlation assumed for symbol pairs absent from the estimate (conservative)",
    )
    CORRELATION_BLOCK_THRESHOLD: float = Field(
        0.5,
        description="If less than this fraction of the new position's risk fits, block the add",
    )

    # Futures position-size gate uses MARGIN (not notional). 1 MES is ~$7,130
    # notional but only ~$1,320 overnight maintenance margin at IBKR. Against a
    # $10K paper account, notional-based math rejects every futures order as
    # "356% of equity"; margin-based math correctly reads as ~13%. This gate
    # defaults to 30% so 1-2 MES contracts approve on a $10K account while
    # still catching genuine oversizing.
    MAX_FUTURES_MARGIN_PCT: float = Field(
        0.30,
        description="Max 30% of portfolio equity as futures initial margin",
    )

    # ── Execution Cost Modeling (Backtests) ──────────────────────────────
    COMMISSION_PER_CONTRACT: float = Field(
        1.42,
        description="MES/MNQ CME round-trip commission ($0.72 exchange + $0.70 clearing)",
    )
    SLIPPAGE_TICKS: float = Field(1.0, description="Conservative 1-tick adverse slippage per fill")
    COMMISSION_ENABLED: bool = Field(True, description="Apply commission in backtests")
    SLIPPAGE_ENABLED: bool = Field(True, description="Apply slippage in backtests")

    # Bid-ask spread modeling (separate from adverse-tick slippage)
    # MES typical spread: 0.25 pts = 1 tick. Half-spread = 0.5 ticks paid on each side.
    SPREAD_TICKS: float = Field(
        0.5,
        description="Half-spread ticks — paid on entry AND exit (0.5 ticks = 1 full tick round-trip)",
    )
    SPREAD_ENABLED: bool = Field(True, description="Apply bid-ask spread simulation in backtests")

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
    TRAILING_STOP_ATR_MULT: float = Field(
        2.0,
        description=(
            "ATR multiplier for the live trailing-stop service. Stop distance = "
            "TRAILING_STOP_ATR_MULT * ATR(14, 1h). Default 2.0 matches the "
            "atr_trail_mult used in trend_signals.py backtests. Tune here to "
            "keep live behaviour in sync with backtested strategy parameters."
        ),
    )
    SESSION_FLATTEN_TIME_ET: str = "15:45"  # Flatten all positions at 3:45 PM ET
    MCL_INVENTORY_BLACKOUT_MINUTES: int = (
        45  # EIA blackout: 15min before + 30min after Wed 10:30 ET
    )

    # ── Infrastructure ────────────────────────────────────────────────────
    SQLITE_DB_PATH: str = Field(
        "data/jarvis_trader.db",
        description=(
            "Canonical SQLite database path. At runtime this is resolved to an "
            "absolute path anchored on engine/ by the _resolve_sqlite_db_path "
            "validator below, regardless of the working directory of the "
            "importing process. Added 2026-04-10 to fix a split-brain DB bug "
            "where processes running from workspace root wrote to "
            "data/jarvis_trader.db while the engine wrote to "
            "engine/data/jarvis_trader.db."
        ),
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
    MTF_FILTER_ENABLED: bool = Field(
        True,
        description=(
            "Enable MTF (multi-timeframe) 4h vs 1h STC alignment pre-filter. "
            "Set to False to bypass when market data is stale or IB Gateway is offline."
        ),
    )
    WATCHLIST_SCAN_ENABLED: bool = Field(
        True,
        description=(
            "Enable hourly watchlist auto-scanner. Set to False to halt the scheduled "
            "pipeline scans without restarting the engine (emergency kill for contaminated "
            "data conditions). Introduced 2026-04-10 after stale-cache trades contaminated paper_trades."
        ),
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
        True,
        description="Require STC signal alignment before pipeline generates a directional signal",
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

    AUTONOMOUS_AUTO_APPROVE_PAPER: bool = Field(
        False,
        description=(
            "When True AND LIVE_TRADING_ENABLED is False, autonomous-scheduler "
            "candidates are auto-approved in paper mode instead of waiting for "
            "human approval (which otherwise expires at the candidate TTL). Feeds "
            "the IC/Brier calibration loop with more paper trades. NEVER affects "
            "live: when LIVE_TRADING_ENABLED is True this flag is ignored and the "
            "human-in-the-loop gate is preserved."
        ),
    )

    ALLOW_PAPER_SIMULATED_ORDERS: bool = Field(
        False,
        description="When True, paper trading mode allows simulated orders via check_order route",
    )

    ALLOW_MOCK_QUOTES: bool = Field(
        False,
        description=(
            "TEST FIXTURES ONLY. When True, IBGatewayConnector.get_quote may fall "
            "back to a frozen static quote table (MES 5300.10, MCL 82.60, ...) if "
            "no real price is available. MUST stay False in every real paper or "
            "live context: until 2026-07-21 this fallback was unconditional, so "
            "every fill booked at a 2024-era constant whenever the market-data "
            "waterfall returned None, manufacturing a 3,475-fill phantom track "
            "record. Production must refuse to fill without a real price basis."
        ),
    )

    # ── HB-1 broker-side bracket orders ────────────────────────────────────
    # When True, approved trades that carry stop_price (and optionally target_price)
    # are submitted via SafetyLayer.submit_entry_with_stop so broker-side STP + TP
    # children are placed atomically with the entry. Default False = legacy behavior
    # (naked entry, engine-side stop polling). Flip on only after a paper smoke test
    # on IBKR port 4002 per the 2026-04-23 HB-1 audit.
    ENABLE_BROKER_BRACKETS: bool = Field(
        True,  # was False — HB-1 audit cleared, smoke test required before flip
        description=(
            "Route approved trades through SafetyLayer.submit_entry_with_stop "
            "to place broker-side STP + TP children atomically with the entry. "
            "Requires approval snapshot to include stop_price; target_price optional."
        ),
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

    # ── Pipeline alert rate limit (WhatsApp / Twilio) ───────────────────────
    # Separate from risk kill-switch params — caps notification spam per symbol.
    ALERT_COOLDOWN_MINUTES: int = Field(
        15,
        ge=1,
        le=10080,
        description=(
            "Minimum minutes between WhatsApp alerts for the same symbol when the "
            "watchlist scheduler or manual scan emits a non-HOLD pipeline decision."
        ),
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
    IBKR_CONNECT_TIMEOUT_SECONDS: float = Field(
        5.0,
        description=(
            "Cap on ib_async TCP handshake during startup. Default 5s keeps "
            "FastAPI lifespan fast when IB Gateway is stopped (dev restarts, "
            "tests). Bump to 10-15s if launching Gateway races engine startup."
        ),
    )
    IB_PAPER_BROKER_ENABLED: bool = Field(
        False,  # P0-2 default OFF — flip only after the broker-observed proof passes
        description=(
            "Attach the real IBGatewayManager (port 4002 paper) to the order path "
            "instead of the in-process IBGatewayConnector simulator. When False, "
            "orders are simulated and never reach a broker. See "
            "docs/ROADMAP_P0-2_SCOPE_2026-07-21.md. [safety-review]"
        ),
    )
    IB_ACCOUNT_ID: str = Field(
        "",
        description="IB paper account id (e.g. DUxxxxxxx) tagged on real order routing when IB_PAPER_BROKER_ENABLED.",
    )

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
    POLYGON_STREAM_ENABLED: bool = Field(
        default=True,
        description="Enable Polygon WebSocket streamer; requires a Polygon plan with WebSocket access",
    )
    FRED_API_KEY: Optional[str] = Field(default=None, description="Federal Reserve FRED API key")
    FINNHUB_API_KEY: Optional[str] = Field(default=None, description="Finnhub API key")
    BRAVE_API_KEY: Optional[str] = Field(
        default=None, description="Brave Search API key for news analyst live web search"
    )
    ALPACA_API_KEY: Optional[str] = Field(default=None, description="Alpaca Markets API key")
    ALPACA_SECRET_KEY: Optional[str] = Field(default=None, description="Alpaca Markets secret key")
    ALPACA_PAPER: bool = Field(default=True, description="Use Alpaca paper trading")

    # ── Multi-Market Activation ──────────────────────────────────────────
    # Consumed by MarketModule.is_enabled() on crypto, options, polymarket.
    # Fields were missing before 2026-04-16 which silently disabled all
    # three modules at runtime (AttributeError swallowed by try/except).
    ENABLED_MARKETS: str = Field(
        default="",
        description=(
            "Comma-separated list of market modules to activate, e.g. "
            "'futures,crypto'. Empty string keeps all non-futures modules "
            "dormant — matches historical behavior."
        ),
    )
    CRYPTO_ENABLED: bool = Field(
        default=False,
        description=(
            "Enable the crypto market module. Also requires CRYPTO_BACKEND "
            "to be set and 'crypto' to appear in ENABLED_MARKETS."
        ),
    )

    # ── Crypto (Kraken or Freqtrade) ─────────────────────────────────────
    CRYPTO_BACKEND: str = Field(
        default="freqtrade",
        description=(
            "Crypto module backend: 'freqtrade' (default, delegates to a "
            "running Freqtrade instance) or 'kraken' (drives kraken-cli "
            "directly with built-in paper engine)."
        ),
    )
    KRAKEN_SPOT_API_KEY: Optional[str] = Field(
        default=None,
        description="Kraken spot API key; only required when CRYPTO_BACKEND=kraken and KRAKEN_LIVE_ENABLED=True",
    )
    KRAKEN_SPOT_API_SECRET: Optional[str] = Field(
        default=None, description="Kraken spot API secret"
    )
    KRAKEN_FUTURES_API_KEY: Optional[str] = Field(
        default=None,
        description="Kraken futures API key (separate from spot); only required when trading futures live",
    )
    KRAKEN_FUTURES_API_SECRET: Optional[str] = Field(
        default=None, description="Kraken futures API secret"
    )
    KRAKEN_LIVE_ENABLED: bool = Field(
        default=False,
        description=(
            "When False, all Kraken trade submissions are routed through "
            "kraken-cli's paper engine regardless of API keys. Mirrors the "
            "IBKR live-gating pattern — flip to True ONLY after paper-phase "
            "validation and ensure WhatsApp approval flow is wired."
        ),
    )

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
    TRADER_MODEL: str = Field("claude-sonnet-4-6", description="Model for trader/risk/fund manager")
    FAST_MODEL: str = Field("claude-haiku-4-5-20251001", description="Model for fast/cheap ops")

    # ── Databases ─────────────────────────────────────────────────────────
    POSTGRES_URL: str = Field("postgresql://jarvis:jarvis@localhost:5432/jarvis_trader")
    REDIS_URL: str = Field("redis://localhost:6379")
    QUESTDB_HOST: str = Field("localhost")
    QUESTDB_PORT: int = Field(9000)

    # ── Notifications (WhatsApp via Twilio / Telegram) ───────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None, description="Twilio account SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None, description="Twilio auth token")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(default=None, description="Twilio WhatsApp sender")
    WHATSAPP_TO: Optional[str] = Field(default=None, description="WhatsApp recipient number")
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, description="Telegram bot token")
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None, description="Default Telegram chat id")

    # ── Shared Messaging Gateway ──────────────────────────────────────────
    MESSAGING_DEFAULT_AGENT: str = Field(
        default="openclaw",
        description="Default shared gateway agent for Telegram/WhatsApp conversations",
    )
    MESSAGING_MAX_HISTORY_MESSAGES: int = Field(
        default=10,
        description="Number of prior messages kept per channel/user/agent session",
    )
    MESSAGING_ALLOWED_TELEGRAM_CHAT_IDS: str = Field(
        default="",
        description="Comma-separated Telegram chat IDs allowed to use the shared gateway",
    )
    MESSAGING_ALLOWED_WHATSAPP_NUMBERS: str = Field(
        default="",
        description="Comma-separated WhatsApp numbers allowed to use the shared gateway",
    )
    OLLAMA_BASE_URL: str = Field(
        default="http://127.0.0.1:11434",
        description="Base URL for the local Ollama runtime used by Hermes fallback/local-first flows",
    )
    OPENCLAW_LOCAL_MODEL: str = Field(
        default="ollama/qwen2.5:7b",
        description="Status/model label for the OpenClaw local-first path",
    )
    OPENCLAW_AGENT_COMMAND_TEMPLATE: str = Field(
        default="openclaw agent --agent main --message {message} --json",
        description="WSL command template used to invoke the OpenClaw agent from the shared gateway",
    )
    OPENCLAW_STATUS_COMMAND: str = Field(
        default="openclaw gateway status",
        description="WSL command used for OpenClaw health/status checks",
    )
    HERMES_LOCAL_MODEL: str = Field(
        default="hermes3",
        description="Local Ollama model used for Hermes local-first messaging",
    )
    HERMES_CLOUD_BASE_URL: Optional[str] = Field(
        default=None,
        description="Optional OpenAI-compatible fallback base URL for Hermes",
    )
    HERMES_CLOUD_MODEL: Optional[str] = Field(
        default=None,
        description="Optional fallback model name for Hermes when local Ollama is unavailable",
    )
    HERMES_CLOUD_API_KEY: Optional[str] = Field(
        default=None,
        description="Optional bearer token for the Hermes cloud fallback endpoint",
    )

    # ── Instruments to Trade ─────────────────────────────────────────────
    FUTURES_WATCHLIST: Union[str, list[str]] = Field(
        default="MCL,MNQ,MES",
        description="Micro futures contracts to trade (comma-separated or list). "
        "MCL first (WFE=0.82), MNQ second (WFE=0.57), MES third (WFE=0.09, paper trading authorized Tier 3 2026-04-09). "
        "All three are active in the FuturesMarketModule.",
    )
    # Options module: dry-run in paper before enabling live routing; see docs/backlog/EPICS_12_17_FOLLOWONS.md
<<<<<<< HEAD
    OPTIONS_WATCHLIST: Union[str, list[str]] = Field(
        default=["SPY", "QQQ", "AAPL", "TSLA"], description="Underlying symbols for options trading"
=======
    # 2026-08-17: AAPL/TSLA REMOVED — daily SMA-trend gate-v2 WFO certification
    # FAILED both (AAPL sample-starvation 1-3 OOS trades; TSLA p_edge 0.50-0.56).
    # SPY/QQQ PASSED (p_edge 0.68-0.73, 15-30 OOS trades). Verdicts in
    # data/gate_v2_verdicts/<SYM>_sma_cert_*.json. SCAN_SYMBOLS unchanged
    # (display-only scanner never routes).
    OPTIONS_WATCHLIST: Union[str, list[str]] = Field(
        default=["SPY", "QQQ"], description="Underlying symbols for options trading"
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    )
    # HiddenPivots scan universe — futures + ETFs + liquid individual names.
    # Display/analysis only (the HP scanner never routes orders), so the roster
    # is intentionally broad and is NOT bound by DO_NOT_TRADE_SYMBOLS. Override
    # via the SCAN_SYMBOLS env var (comma-separated or JSON array).
    SCAN_SYMBOLS: Union[str, list[str]] = Field(
        default=(
            "MES,MNQ,MGC,MCL,"
            "SPY,QQQ,IWM,DIA,GLD,SLV,SMH,XLE,"
            "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,AVGO,NFLX,"
            "PLTR,COIN,MSTR,MU,CRM,UBER,JPM,BAC,XOM,LLY,COST"
        ),
        description="HiddenPivots scan universe (comma-separated or list): "
        "futures, ETFs, and liquid single-name equities. Analysis-only.",
    )

    @field_validator("FUTURES_WATCHLIST", "OPTIONS_WATCHLIST", "SCAN_SYMBOLS", mode="before")
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

    @field_validator("SQLITE_DB_PATH")
    @classmethod
    def _resolve_sqlite_db_path(cls, v: str) -> str:
        """
        Resolve SQLITE_DB_PATH to an absolute path anchored on the engine/
        directory, regardless of the caller's working directory.

        Rationale: the previous default "data/jarvis_trader.db" was a
        *relative* path. When the engine ran with cwd=engine/, it resolved
        to engine/data/jarvis_trader.db (correct). When other tools or
        subprocesses ran with cwd=workspace-root, the same string resolved
        to workspace-root/data/jarvis_trader.db (a different DB file),
        producing a split-brain where Discord data and paper trades
        landed in different databases. 2026-04-10 fix.
        """
        from pathlib import Path as _Path

        p = _Path(v)
        if p.is_absolute():
            return str(p)

        # Anchor at engine/ regardless of cwd:
        # config.py lives at engine/config.py → parent = engine/
        engine_root = _Path(__file__).resolve().parent
        return str(engine_root / v)

    @field_validator("MAX_CONTRACTS_PER_INSTRUMENT")
    @classmethod
    def _enforce_max_contracts_hard_cap(cls, v: int) -> int:
        """Clamp to [1, 20]. Phase 3 authorizes up to 20 micro contracts per instrument."""
        import logging as _logging

        try:
            n = int(v)
        except (TypeError, ValueError):
            n = 2
        if n > 20:
            _logging.getLogger(__name__).warning(
                "MAX_CONTRACTS_PER_INSTRUMENT=%s from env exceeds hard cap of 20 — clamping to 20",
                n,
            )
            return 20
        return max(1, n)

    def get_enabled_markets(self) -> list[str]:
        """
        Parse ENABLED_MARKETS into a list of lowercase module names.

        Returns an empty list when the env var is unset or blank — which
        keeps crypto/options/polymarket dormant unless explicitly opted in.
        """
        raw = (self.ENABLED_MARKETS or "").strip()
        if not raw:
            return []
        return [m.strip().lower() for m in raw.split(",") if m.strip()]

    def get_adaptive_stc(self, symbol: str, timeframe: str) -> dict:
        """
        Dynamically loads the most recent STC thresholds from the async
        walk-forward optimizer state bank. If missing or stale/corrupt,
        safely falls back to the .env static Baseline metrics.
        """
        import json
        from pathlib import Path

        baseline = {"stc_os": self.STC_OVERSOLD, "stc_ob": self.STC_OVERBOUGHT}
        state_path = Path(__file__).parent / "data" / "adaptive_config.json"

        if not state_path.exists():
            return baseline

        try:
            with open(state_path, "r") as f:
                state = json.load(f)

            # Navigate schema: state["MNQ"]["15m"]
            symbol_data = state.get(symbol.upper(), {})
            tf_data = symbol_data.get(timeframe.lower(), {})

            if "stc_os" in tf_data and "stc_ob" in tf_data:
                return {"stc_os": float(tf_data["stc_os"]), "stc_ob": float(tf_data["stc_ob"])}
            return baseline
        except Exception:
            return baseline

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
