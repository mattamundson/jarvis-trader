"""
Engine Startup Validation — runs at boot to catch misconfigurations early.

Usage:
    from startup_checks import run_startup_checks
    results = run_startup_checks(config)
    for r in results:
        if r.status == "fail": logger.error(r)
"""

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Single startup check result."""

    name: str
    status: Literal["pass", "warn", "fail"]
    message: str

    def __str__(self) -> str:
        """String representation for logging."""
        return f"[{self.status.upper()}] {self.name}: {self.message}"


def run_startup_checks(config) -> list[CheckResult]:
    """Run all startup validation checks against the given config."""
    results = []
    results.append(_check_api_key(config))
    results.append(_check_ibkr_port(config))
    results.append(_check_live_trading_disabled(config))
    results.append(_check_human_approval(config))
    results.append(_check_database(config))
    results.append(_check_polygon_key(config))
    results.append(_check_fred_key(config))
    results.append(_check_disk_space())
    results.append(_check_paper_config_do_not_trade_sync())
    results.append(_check_autonomous_active_symbols())

    for r in results:
        if r.status == "fail":
            logger.error("[STARTUP FAIL] %s: %s", r.name, r.message)
        elif r.status == "warn":
            logger.warning("[STARTUP WARN] %s: %s", r.name, r.message)
        else:
            logger.info("[STARTUP OK] %s: %s", r.name, r.message)

    return results


def _check_api_key(config) -> CheckResult:
    """
    FAIL if API_KEY is not set or is a known placeholder.
    """
    api_key = getattr(config, "API_KEY", None)

    if not api_key:
        return CheckResult(
            name="API Key",
            status="fail",
            message="API_KEY not set. Edit .env and set API_KEY to a strong random value.",
        )

    if api_key == "CHANGE_ME_BEFORE_DEPLOY":
        return CheckResult(
            name="API Key",
            status="fail",
            message="API_KEY is placeholder 'CHANGE_ME_BEFORE_DEPLOY'. Edit .env with real value.",
        )

    return CheckResult(
        name="API Key",
        status="pass",
        message="API_KEY is set",
    )


def _check_ibkr_port(config) -> CheckResult:
    """
    FAIL if port is 4001 (live trading).
    PASS if port is 4002 (paper trading).
    WARN if port is something else.
    """
    port = getattr(config, "IBKR_PORT", None)

    if port == 4001:
        return CheckResult(
            name="IBKR Port",
            status="fail",
            message="IBKR_PORT is 4001 (live trading). Must use 4002 (paper) during paper phase.",
        )

    if port == 4002:
        return CheckResult(
            name="IBKR Port",
            status="pass",
            message="IBKR_PORT is 4002 (paper mode)",
        )

    return CheckResult(
        name="IBKR Port",
        status="warn",
        message=f"IBKR_PORT is {port} (unexpected value, expected 4001 or 4002)",
    )


def _check_live_trading_disabled(config) -> CheckResult:
    """
    FAIL if LIVE_TRADING_ENABLED is True.
    """
    live_enabled = getattr(config, "LIVE_TRADING_ENABLED", False)

    if live_enabled:
        return CheckResult(
            name="Live Trading",
            status="fail",
            message="LIVE_TRADING_ENABLED is True. Must be False during paper phase.",
        )

    return CheckResult(
        name="Live Trading",
        status="pass",
        message="Live trading disabled (paper mode active)",
    )


def _check_human_approval(config) -> CheckResult:
    """
    FAIL if REQUIRE_HUMAN_APPROVAL is False.
    """
    human_approval = getattr(config, "REQUIRE_HUMAN_APPROVAL", True)

    if not human_approval:
        return CheckResult(
            name="Human Approval",
            status="fail",
            message="REQUIRE_HUMAN_APPROVAL is False. All trades must require human approval.",
        )

    return CheckResult(
        name="Human Approval",
        status="pass",
        message="Human approval required for all trades",
    )


def _check_database(config) -> CheckResult:
    """
    WARN if SQLite database file doesn't exist yet.
    PASS if it exists or will be created on first run.
    """
    db_path = getattr(config, "SQLITE_DB_PATH", "data/jarvis_trader.db")

    if os.path.exists(db_path):
        return CheckResult(
            name="SQLite Database",
            status="pass",
            message=f"Database exists at {db_path}",
        )

    # Database doesn't exist yet — will be created on startup
    return CheckResult(
        name="SQLite Database",
        status="warn",
        message=f"Database not found at {db_path} — will be created on startup",
    )


def _check_polygon_key(config) -> CheckResult:
    """
    WARN if POLYGON_API_KEY is not set.
    """
    polygon_key = getattr(config, "POLYGON_API_KEY", None)

    if not polygon_key:
        return CheckResult(
            name="Polygon API Key",
            status="warn",
            message="POLYGON_API_KEY not set. Data tier 2 unavailable; only IBKR and CSV cache.",
        )

    return CheckResult(
        name="Polygon API Key",
        status="pass",
        message="Polygon API key configured",
    )


def _check_fred_key(config) -> CheckResult:
    """
    WARN if FRED_API_KEY is not set.
    """
    fred_key = getattr(config, "FRED_API_KEY", None)

    if not fred_key:
        return CheckResult(
            name="FRED API Key",
            status="warn",
            message="FRED_API_KEY not set. Macro data unavailable (optional feature).",
        )

    return CheckResult(
        name="FRED API Key",
        status="pass",
        message="FRED API key configured",
    )


def _check_paper_config_do_not_trade_sync() -> CheckResult:
    """
    FAIL if any paper config has enabled=True for a symbol in DO_NOT_TRADE_SYMBOLS.

    Root cause of the MNQ wiring leak (commit 0772e20, 2026-05-06/07): the
    paper config had enabled=True while the symbol was in DO_NOT_TRADE_SYMBOLS.
    The dispatcher trusted the config flag without cross-checking the verdict
    blocklist, causing 55 erroneous trades. This check makes the misconfiguration
    visible at cold-start before any signals can fire.
    """
    try:
        from backtest.paper_config import FIFTEEN_MIN_CONFIGS, PAPER_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError as exc:
        return CheckResult(
            name="Paper Config / DO_NOT_TRADE Sync",
            status="warn",
            message=f"Could not import paper_config or signals: {exc}",
        )

    violations: list[str] = []

    all_configs = list(PAPER_CONFIGS.items()) + [
        (sym, cfg) for sym, cfg in FIFTEEN_MIN_CONFIGS.items()
        if sym not in PAPER_CONFIGS  # avoid double-counting same symbol
    ]

    for sym, cfg in all_configs:
        if cfg.get("enabled", False) and sym in DO_NOT_TRADE_SYMBOLS:
            interval = cfg.get("interval", "?")
            violations.append(f"{sym} ({interval}): enabled=True but in DO_NOT_TRADE_SYMBOLS")

    # Also check FIFTEEN_MIN_CONFIGS separately (same symbol may have multiple timeframes)
    for sym, cfg in FIFTEEN_MIN_CONFIGS.items():
        if cfg.get("enabled", False) and sym in DO_NOT_TRADE_SYMBOLS:
            interval = cfg.get("interval", "?")
            entry = f"{sym} ({interval}, 15m cfg): enabled=True but in DO_NOT_TRADE_SYMBOLS"
            if entry not in violations:
                violations.append(entry)

    if violations:
        return CheckResult(
            name="Paper Config / DO_NOT_TRADE Sync",
            status="fail",
            message=(
                f"{len(violations)} config(s) enabled for DO_NOT_TRADE symbol(s): "
                + "; ".join(violations)
                + ". Fix: set enabled=False in engine/backtest/paper_config.py "
                "or remove the symbol from DO_NOT_TRADE_SYMBOLS in signals.py."
            ),
        )

    return CheckResult(
        name="Paper Config / DO_NOT_TRADE Sync",
        status="pass",
        message=(
            f"All {len(all_configs)} paper configs are consistent with "
            f"DO_NOT_TRADE_SYMBOLS ({set(DO_NOT_TRADE_SYMBOLS)})"
        ),
    )


def _check_autonomous_active_symbols() -> CheckResult:
    """
    WARN if AUTONOMOUS_ACTIVE_SYMBOLS members are in DO_NOT_TRADE_SYMBOLS.

    Such symbols are gated to NO_TRADE, so the autonomous loop silently no-ops
    on them — the MCL,MNQ default is exactly this dead config (both blocked, the
    loop can never fire). The scheduler already WARNs at injection time
    (pipeline_autonomous._warn_blocked_active_symbols), but that runs after the
    boot orchestrator; promoting the check here makes the dead config loud at
    cold-start alongside the rest of startup validation. Only meaningful when the
    autonomous pipeline is enabled.
    """
    name = "Autonomous Active Symbols"
    enabled = os.getenv("ENABLE_AUTONOMOUS_PIPELINE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return CheckResult(
            name=name,
            status="pass",
            message="autonomous pipeline disabled — active-symbol check skipped",
        )

    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError as exc:
        return CheckResult(
            name=name, status="warn", message=f"Could not import signals: {exc}"
        )

    raw = os.getenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MCL,MNQ").strip()
    active = [s.strip().upper() for s in raw.split(",") if s.strip()]
    blocked = [s for s in active if s in DO_NOT_TRADE_SYMBOLS]
    tradeable = [s for s in active if s not in DO_NOT_TRADE_SYMBOLS]

    if blocked and not tradeable:
        return CheckResult(
            name=name,
            status="warn",
            message=(
                f"ALL active symbols {active} are in DO_NOT_TRADE_SYMBOLS "
                f"({set(DO_NOT_TRADE_SYMBOLS)}) — the autonomous loop can NEVER "
                "trade (every candidate is gated to NO_TRADE). Set "
                "AUTONOMOUS_ACTIVE_SYMBOLS to tradeable symbols (e.g. MES,MGC)."
            ),
        )
    if blocked:
        return CheckResult(
            name=name,
            status="warn",
            message=(
                f"Active symbols {blocked} are in DO_NOT_TRADE_SYMBOLS and will "
                f"never trade; tradeable subset that can fire: {tradeable}."
            ),
        )
    return CheckResult(
        name=name,
        status="pass",
        message=f"All active symbols {active} are tradeable (not in DO_NOT_TRADE_SYMBOLS)",
    )


def _check_disk_space() -> CheckResult:
    """
    WARN if disk space < 1GB free.
    """
    try:
        usage = shutil.disk_usage("/")
        free_bytes = usage.free
        free_gb = free_bytes / (1024**3)

        if free_gb < 1.0:
            return CheckResult(
                name="Disk Space",
                status="warn",
                message=f"Less than 1GB free ({free_gb:.2f}GB available). Logs may fill disk.",
            )

        return CheckResult(
            name="Disk Space",
            status="pass",
            message=f"{free_gb:.2f}GB free",
        )
    except OSError as e:
        # If we can't check disk space, warn but don't fail
        return CheckResult(
            name="Disk Space",
            status="warn",
            message=f"Could not check disk space: {e}",
        )
