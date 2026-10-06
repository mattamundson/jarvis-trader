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
    FAIL if execution port is 4001 (live trading).
    PASS if execution port is 4002 (paper trading).
    WARN if execution port is something else.

    When IBKR_MARKET_DATA_PORT is set to 4001 for read-only market data
    while IBKR_PORT remains 4002, that is allowed.
    """
    exec_port = getattr(config, "IBKR_PORT", None)
    data_port = getattr(config, "IBKR_MARKET_DATA_PORT", None)

    # Check execution port (order/account-mutating path)
    if exec_port == 4001:
        return CheckResult(
            name="IBKR Port",
            status="fail",
            message="IBKR_PORT is 4001 (live trading). Must use 4002 (paper) during paper phase.",
        )

    if exec_port == 4002:
        # Execution is paper — check if data port is separately configured
        if data_port == 4001:
            return CheckResult(
                name="IBKR Port",
                status="pass",
                message="IBKR_PORT is 4002 (paper execution), IBKR_MARKET_DATA_PORT is 4001 (read-only market data from live Gateway)",
            )
        return CheckResult(
            name="IBKR Port",
            status="pass",
            message="IBKR_PORT is 4002 (paper mode)",
        )

    return CheckResult(
        name="IBKR Port",
        status="warn",
        message=f"IBKR_PORT is {exec_port} (unexpected value, expected 4001 or 4002)",
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
    WARN (non-blocking) if REQUIRE_HUMAN_APPROVAL is False.

    Owner directive (2026-06-15): autonomous trading is enabled — trades execute
    without human approval. This was previously a boot-blocking FAIL; it is now a
    loud WARN so the engine boots in autonomous mode while keeping the state
    visible in startup logs. LIVE_TRADING_ENABLED remains separately enforced
    (see _check_live_trading_disabled), so auto-execution stays paper-only.
    """
    human_approval = getattr(config, "REQUIRE_HUMAN_APPROVAL", True)

    if not human_approval:
        return CheckResult(
            name="Human Approval",
            status="warn",
            message=(
                "REQUIRE_HUMAN_APPROVAL is False — AUTONOMOUS trading active, "
                "trades execute without human approval (paper-only while "
                "LIVE_TRADING_ENABLED is False)."
            ),
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


# ---------------------------------------------------------------------------
# Post-init self-check (I3) -- runs at the END of heavy background init.
# run_startup_checks() above validates config BEFORE subsystems exist; this
# block re-asserts live state AFTER they are up so silent degradation (flags
# table missing, RL gate flipped, fidelity collector off, provider chain
# unkeyed) is visible at every boot.
# ---------------------------------------------------------------------------


def run_post_init_selfcheck(config) -> list[CheckResult]:
    """Run post-initialization invariant checks against live engine state."""
    return [
        _selfcheck_flags_table(),
        _selfcheck_rl_gate(),
        _selfcheck_fidelity_collector(config),
        _selfcheck_do_not_trade(),
        _selfcheck_trading_mode(config),
        _selfcheck_llm_provider_chain(config),
    ]


def log_post_init_selfcheck(config) -> list[CheckResult]:
    """Run the post-init self-check and emit one structured log block.

    Every result appears in a single INFO block; each warn/fail additionally
    gets its own WARNING line so log scanners catch the specific item.
    """
    results = run_post_init_selfcheck(config)
    logger.info(
        "STARTUP SELF-CHECK (post-init invariants)\n    %s",
        "\n    ".join(str(r) for r in results),
    )
    for r in results:
        if r.status in ("warn", "fail"):
            logger.warning("[SELF-CHECK %s] %s: %s", r.status.upper(), r.name, r.message)
    return results


def _selfcheck_flags_table() -> CheckResult:
    """WARN if the feature_flags registry/table is not readable."""
    name = "Flags Table"
    try:
        from flags.registry import get_flags

        listed = get_flags().list_flags()
        return CheckResult(
            name=name,
            status="pass",
            message=f"feature_flags registry readable ({len(listed)} flags)",
        )
    except Exception as exc:
        return CheckResult(
            name=name,
            status="warn",
            message=f"feature_flags registry not readable: {exc}",
        )


def _selfcheck_rl_gate() -> CheckResult:
    """WARN if ENABLE_RL_TRADING is ON (expected OFF during paper phase)."""
    name = "RL Gate"
    try:
        from flags.registry import get_flags

        enabled = get_flags().is_enabled("ENABLE_RL_TRADING")
    except Exception as exc:
        return CheckResult(
            name=name,
            status="warn",
            message=f"could not read ENABLE_RL_TRADING: {exc}",
        )
    if enabled:
        return CheckResult(
            name=name,
            status="warn",
            message=(
                "ENABLE_RL_TRADING is ON -- RL executor can influence paper "
                "decisions; confirm this is intentional (expected OFF)"
            ),
        )
    return CheckResult(
        name=name,
        status="pass",
        message="ENABLE_RL_TRADING=False (RL executor gated off, expected)",
    )


def _selfcheck_fidelity_collector(config) -> CheckResult:
    """WARN if ALLOW_PAPER_SIMULATED_ORDERS reverted to False.

    The flag was deliberately flipped True on 2026-06-04 so approved paper
    trades route to real IB paper fills and the execution-fidelity collector
    measures real fill quality. A silent revert (e.g. .env loss) starves the
    fidelity harness without any other symptom.
    """
    name = "Fidelity Collector"
    allow_sim = bool(getattr(config, "ALLOW_PAPER_SIMULATED_ORDERS", False))
    if allow_sim:
        return CheckResult(
            name=name,
            status="pass",
            message=(
                "ALLOW_PAPER_SIMULATED_ORDERS=True -- approved paper trades "
                "route to real IB paper fills (fidelity collector measuring real fills)"
            ),
        )
    return CheckResult(
        name=name,
        status="warn",
        message=(
            "ALLOW_PAPER_SIMULATED_ORDERS=False -- fills are internally "
            "simulated; execution-fidelity collector receives NO real-fill "
            "data (deliberately True since 2026-06-04; investigate if unexpected)"
        ),
    )


def _selfcheck_do_not_trade() -> CheckResult:
    """Report the active DO_NOT_TRADE_SYMBOLS blocklist."""
    name = "DO_NOT_TRADE List"
    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError as exc:
        return CheckResult(
            name=name, status="warn", message=f"could not import signals: {exc}"
        )
    return CheckResult(
        name=name,
        status="pass",
        message=f"DO_NOT_TRADE_SYMBOLS={sorted(DO_NOT_TRADE_SYMBOLS)}",
    )


def _selfcheck_trading_mode(config) -> CheckResult:
    """WARN if live trading is enabled or human approval is disabled.

    run_startup_checks() hard-fails boot on these, but this re-asserts from
    the live settings object after all init completed.
    """
    name = "Trading Mode"
    live = bool(getattr(config, "LIVE_TRADING_ENABLED", False))
    approval = bool(getattr(config, "REQUIRE_HUMAN_APPROVAL", True))
    problems = []
    if live:
        problems.append("LIVE_TRADING_ENABLED=True (must be False in paper phase)")
    if not approval:
        problems.append("REQUIRE_HUMAN_APPROVAL=False (must be True)")
    if problems:
        return CheckResult(name=name, status="warn", message="; ".join(problems))
    return CheckResult(
        name=name,
        status="pass",
        message="paper mode, human approval required for all trades",
    )


def _selfcheck_llm_provider_chain(config) -> CheckResult:
    """Summarize the configured LLM fallback chain; WARN on 0-1 usable legs.

    Boot-time check is keys/flags only -- credit exhaustion is a runtime
    condition surfaced by /health (llm_path_healthy) and the daily digest's
    llm_provider_health block.
    """
    name = "LLM Provider Chain"

    def _key_present(var: str) -> bool:
        value = getattr(config, var, None) or os.getenv(var) or ""
        return bool(str(value).strip())

    anthropic = _key_present("ANTHROPIC_API_KEY")
    google = _key_present("GOOGLE_API_KEY")
    openai_key = _key_present("OPENAI_API_KEY")
    vertex = os.getenv("JARVIS_LLM_VERTEX_FAILOVER", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    chain = (
        f"anthropic(key={'yes' if anthropic else 'NO'}) -> "
        f"vertex(failover={'armed' if vertex else 'off'}) -> "
        f"gemini(key={'yes' if google else 'NO'}) -> "
        f"openai(key={'yes' if openai_key else 'NO'})"
    )
    legs = sum([anthropic, vertex, google, openai_key])
    if legs == 0:
        return CheckResult(
            name=name,
            status="warn",
            message=f"NO LLM provider configured -- every pipeline decision will fail. {chain}",
        )
    if legs == 1:
        return CheckResult(
            name=name,
            status="warn",
            message=f"single-leg LLM chain -- one provider outage stops all decisions. {chain}",
        )
    return CheckResult(name=name, status="pass", message=chain)
