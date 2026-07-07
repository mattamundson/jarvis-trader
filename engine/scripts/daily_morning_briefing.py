"""
Daily morning briefing for JARVIS TRADER.

Runs at 09:00 ET on weekdays. Assembles a forward-looking Markdown brief
covering engine status, active strategies, overnight bar regime, Discord
overnight signal summary, strategy expectations, yesterday's post-trade
report link, open positions, and attention items.

Sections
--------
  1. Engine Status           — /health (status, llm, tv, ibkr, kill_switch, uptime)
  2. Active Strategies       — enabled paper configs with verdict freshness
  3. Overnight Bar Regime    — latest 1h bar per active symbol: regime/bias/close/ATR
  4. Discord Overnight Signal — last 16h from discord_corey_commentary FTS
  5. Calendar / Events       — placeholder (v1)
  6. Strategy Expectations   — SMA spread, trending/chopping, crossover proximity
  7. Yesterday's Tally       — link to post_trade_reports/<yesterday>.md
  8. Open Positions          — /brokers/positions or paper_trade tracker
  9. Attention Required      — DO_NOT_TRADE drift, expiring verdicts, degraded health

Usage
-----
    python -m engine.scripts.daily_morning_briefing               # today
    python -m engine.scripts.daily_morning_briefing --date 2026-05-07
    python -m engine.scripts.daily_morning_briefing --no-discord  # skip webhook post
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# Keep httpx/httpcore quiet: their INFO "HTTP Request: POST <url>" line logs the
# full Discord webhook URL (a secret) into stdout and the scheduled-task log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("daily_morning_briefing")

# ---------------------------------------------------------------------------
# Path bootstrap — same pattern as all scripts in this directory
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc

_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_BRIEFING_DIR = _ENGINE_DIR / "data" / "morning_briefings"
_POST_TRADE_DIR = _ENGINE_DIR / "data" / "post_trade_reports"
_GATE_V2_DIR = _ENGINE_DIR / "data" / "gate_v2_verdicts"

_ENGINE_HEALTH_URL = "http://127.0.0.1:8010/health"
_ENGINE_POSITIONS_URL = "http://127.0.0.1:8010/brokers/positions"

_HTTP_TIMEOUT_S = 5

DO_NOT_TRADE_SYMBOLS: frozenset[str] = frozenset({"MCL", "MNQ", "M2K"})

# Verdict freshness window — warn if expiring within this many days
_VERDICT_WARN_DAYS = 7
# Verdict TTL — standard 30-day window referenced in gate v2
_VERDICT_TTL_DAYS = 30

# Number of bars to keep for regime / SMA computation
_SMA_LOOKBACK_BARS = 250  # >200 (slow SMA) + buffer

# Overnight Discord window — hours before briefing time to pull commentary
_OVERNIGHT_HOURS = 16

# ---------------------------------------------------------------------------
# Section A — Engine Status
# ---------------------------------------------------------------------------


def fetch_engine_health(timeout: int = _HTTP_TIMEOUT_S) -> dict[str, Any]:
    """
    Call /health and return the parsed JSON dict.
    Returns a synthetic error dict on timeout / connection failure.
    """
    try:
        with urlopen(_ENGINE_HEALTH_URL, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        return data
    except (URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Engine health check failed: %s", exc)
        return {"status": "UNREACHABLE", "error": str(exc)}


def render_engine_status(health: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append("## 1. Engine Status")
    status = health.get("status", "UNKNOWN")
    status_icon = "OK" if status == "ok" else "DEGRADED"
    lines.append(f"**Status:** {status_icon} (`{status}`)")

    if status == "UNREACHABLE":
        lines.append(f"*Engine unreachable: {health.get('error', 'no detail')}*")
        lines.append("")
        return lines

    fields = [
        ("LLM path", "llm_path_healthy"),
        ("TradingView MCP", "tradingview_mcp_healthy"),
        ("IBKR data", "ibkr_data_connected"),
        ("IBKR exec", "ibkr_execution_connected"),
        ("Kill switch", "kill_switch_active"),
    ]
    for label, key in fields:
        val = health.get(key)
        if val is None:
            display = "—"
        elif isinstance(val, bool):
            display = "YES" if val else "NO"
        else:
            display = str(val)
        lines.append(f"- {label}: **{display}**")

    uptime = health.get("uptime_seconds") or health.get("uptime")
    if uptime is not None:
        try:
            s = int(uptime)
            h, rem = divmod(s, 3600)
            m = rem // 60
            lines.append(f"- Uptime: **{h}h {m}m**")
        except (ValueError, TypeError):
            lines.append(f"- Uptime: **{uptime}**")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section B — Active Strategies
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Section — Key Levels (JARVIS, deterministic)
# ---------------------------------------------------------------------------

# Micros carry the DB bars; ES/NQ are price-identical relabels (and match Corey).
_LEVELS_SYMBOLS: tuple[str, ...] = ("MES", "MNQ", "MGC")
_LEVELS_LABELS: dict[str, str] = {"MES": "ES (via MES)", "MNQ": "NQ (via MNQ)", "MGC": "MGC"}
# 1h bars to pull for the daily resample — ~50 trading days (futures ~23h/day).
_LEVELS_LOOKBACK_1H = 1200


def compute_key_levels(
    symbols: tuple[str, ...] = _LEVELS_SYMBOLS, db_path: Path | None = None
) -> dict[str, Any]:
    """Compute deterministic structural levels per symbol from DB bars.

    Returns {symbol: MorningLevels | None}. Offline: reuses
    analytics.regime.load_recent_bars (1h) + morning_levels.resample_ohlc_to_daily.
    """
    try:
        from analysis.morning_levels import compute_levels_from_bars, resample_ohlc_to_daily
        from analytics.regime import load_recent_bars
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("Key Levels unavailable — import failed: %s", exc)
        return dict.fromkeys(symbols)

    out: dict[str, Any] = {}
    for sym in symbols:
        df1h = load_recent_bars(sym, n_bars=_LEVELS_LOOKBACK_1H, db_path=db_path or _DB_PATH)
        if df1h is None or len(df1h) == 0:
            out[sym] = None
            continue
        daily = resample_ohlc_to_daily(df1h)
        if daily is None or len(daily) < 2:
            out[sym] = None
            continue
        # Drop today's still-forming session so pivots use the last COMPLETED
        # session (the brief runs pre-open; today's partial bar would be H=L=C).
        today_et = datetime.now(_ET).date()
        completed = daily[daily.index.date < today_et]
        use_df = completed if len(completed) >= 2 else daily
        try:
            out[sym] = compute_levels_from_bars(sym, use_df, atr_period=14)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Key Levels compute failed for %s: %s", sym, exc)
            out[sym] = None
    return out


def _fmt_levels(vals: list[float] | None) -> str:
    if not vals:
        return "—"
    return " / ".join(f"{v:.2f}" for v in vals)


def render_key_levels(levels_map: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append("## Key Levels (JARVIS)")
    lines.append(
        "*Deterministic from real bars (floor pivots + Wilder ATR). "
        "MES≈ES, MNQ≈NQ. This is math, not a discretionary read.*"
    )
    lines.append("")
    lines.append(
        "| Instrument | Pivot | R1 / S1 | R2 / S2 | ATR | Upside targets | Downside targets |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for sym in _LEVELS_SYMBOLS:
        label = _LEVELS_LABELS.get(sym, sym)
        lv = levels_map.get(sym)
        if lv is None:
            lines.append(f"| {label} | *no bars* | — | — | — | — | — |")
            continue
        atr_str = f"{lv.atr:.2f}" if lv.atr == lv.atr else "—"  # NaN-safe
        lines.append(
            f"| {label} | {lv.pivot:.2f} | {lv.r1:.2f} / {lv.s1:.2f} | "
            f"{lv.r2:.2f} / {lv.s2:.2f} | {atr_str} | "
            f"{_fmt_levels(lv.targets_up)} | {_fmt_levels(lv.targets_down)} |"
        )
    lines.append("")
    return lines


def _persist_forecast(
    briefing_date: date,
    levels_map: dict[str, Any],
    read: dict[str, Any] | None = None,
) -> None:
    """Persist today's levels (+ JARVIS's Read) to the forecast journal + a JSON
    backup. Best-effort: any failure here is logged and swallowed so it never
    breaks the brief. The Read is attached to the anchor symbol's row only."""
    try:
        from analysis.forecast_journal import upsert_forecast, write_json_backup
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("forecast journal unavailable: %s", exc)
        return
    date_str = briefing_date.isoformat()
    ts = datetime.now(_UTC).isoformat()
    # Only persist a real read (skip the 'none' fallback stub).
    store_read = read if (read and read.get("data_quality") != "none") else None
    bundle: dict[str, Any] = {"date": date_str, "generated_ts": ts, "symbols": {}}
    if store_read is not None:
        bundle["read"] = store_read
    for sym, lv in levels_map.items():
        if lv is None:
            continue
        levels_dict = lv.to_dict()
        read_for_sym = store_read if sym == _READ_ANCHOR else None
        try:
            upsert_forecast(date_str, sym, levels_dict, ts, read=read_for_sym, db_path=_DB_PATH)
            bundle["symbols"][sym] = {"levels": levels_dict}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("journal upsert failed for %s: %s", sym, exc)
    try:
        write_json_backup(date_str, bundle)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("json backup failed: %s", exc)


# ---------------------------------------------------------------------------
# JARVIS's Read — a labeled discretionary opinion (LLM, display/journal only)
# ---------------------------------------------------------------------------

# Anchor the daily Read on the broad equity index (ES via MES); stored on that
# journal row and graded against MES outcome by the evening scorer.
_READ_ANCHOR = "MES"


def _read_fallback(reason: str) -> dict[str, Any]:
    return {
        "bias": "neutral",
        "conviction": 0.0,
        "key_levels_committed": [],
        "scenario_if_above": "",
        "scenario_if_below": "",
        "narrative": f"No read available ({reason}).",
        "data_quality": "none",
    }


def compute_jarvis_read(
    briefing_date: date,
    levels_map: dict[str, Any],
    regime_map: dict[str, dict],
) -> dict[str, Any]:
    """Generate JARVIS's discretionary read for the session (LLM, best-effort).

    Always returns a dict; on any failure (import, no API key, LLM error) it
    returns an honest 'no read' stub rather than fabricating an opinion.
    """
    try:
        from analysis.jarvis_read import generate_read
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("JARVIS's Read unavailable — import failed: %s", exc)
        return _read_fallback("import error")

    # Ensure the API key is loaded from engine/.env when not already in the
    # environment (the scheduled task may or may not pre-load secrets). Absolute
    # path so it works regardless of CWD. App loading its own config; no secret
    # is logged or echoed.
    if not os.getenv("ANTHROPIC_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(_ENGINE_DIR / ".env", override=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(".env load for read skipped: %s", exc)

    # Fold in the Phase E calibrator's feedback so the Read self-corrects.
    hint = ""
    shrink = 1.0
    try:
        from analytics.morning_levels_calibrator import calibration_hint, load_state

        state = load_state()
        if state:
            hint = calibration_hint(state)
            shrink = float((state.get("read_calibration") or {}).get("conviction_shrink", 1.0))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("calibrator state unavailable: %s", exc)

    import asyncio

    try:
        return asyncio.run(
            generate_read(
                briefing_date.isoformat(),
                levels_map,
                regime_map,
                calibration_hint=hint,
                conviction_shrink=shrink,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("JARVIS's Read generation failed: %s", exc)
        return _read_fallback("error")


def render_jarvis_read(read: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    lines.append("## JARVIS's Read")
    lines.append(
        "*JARVIS's own labeled opinion for the session — a discretionary lean, "
        "NOT a fact and NOT a trade signal. Graded against the close each evening "
        "so the track record is honest.*"
    )
    lines.append("")

    if not read or read.get("data_quality") == "none":
        reason = (read or {}).get("narrative") or "No read available."
        lines.append(f"*{reason}*")
        lines.append("")
        return lines

    bias = str(read.get("bias", "neutral")).upper()
    conv = float(read.get("conviction", 0.0) or 0.0)
    conv_10 = round(conv * 10)
    lines.append(f"**Lean:** {bias}  |  **Conviction:** {conv_10}/10")
    lines.append("")

    narrative = str(read.get("narrative", "")).strip()
    if narrative:
        lines.append(narrative)
        lines.append("")

    above = str(read.get("scenario_if_above", "")).strip()
    below = str(read.get("scenario_if_below", "")).strip()
    if above:
        lines.append(f"- **If accepted above pivot/trigger:** {above}")
    if below:
        lines.append(f"- **If held/broken below:** {below}")
    committed = read.get("key_levels_committed") or []
    if committed:
        watching = " / ".join(f"{v:g}" for v in committed)
        lines.append(f"- **Watching:** {watching}")
    lines.append("")
    return lines


def compute_corey_compare(
    briefing_date: date,
    read: dict[str, Any] | None,
    levels_map: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare JARVIS's Read with Corey's session bias. Returns None when Corey's
    feed is dry (Phase F is dormant until the Discord token is refreshed)."""
    try:
        from analysis.corey_compare import compare, fetch_corey_bias
    except ImportError as exc:  # pragma: no cover - defensive
        logger.debug("corey_compare unavailable: %s", exc)
        return None

    corey = fetch_corey_bias(briefing_date.isoformat(), db_path=str(_DB_PATH))
    if not corey:
        return None  # dormant — no section rendered

    anchor = levels_map.get(_READ_ANCHOR)
    jarvis_levels: list[float] = []
    if anchor is not None:
        for k in ("pivot", "r1", "s1", "r2", "s2"):
            v = getattr(anchor, k, None)
            if v is not None:
                jarvis_levels.append(float(v))
    return compare(read, corey, jarvis_levels=jarvis_levels)


def load_active_strategies() -> list[dict[str, Any]]:
    """
    Return a list of enabled strategy configs with verdict freshness info.

    Each entry has keys: symbol, strategy, fast, slow, verdict_file,
    verdict, passed_via, created_at, days_since_created, days_until_expiry.
    """
    try:
        from backtest.paper_config import PAPER_CONFIGS
    except ImportError:
        logger.warning("paper_config not importable — active strategies unavailable")
        return []

    active: list[dict[str, Any]] = []

    for sym, cfg in PAPER_CONFIGS.items():
        if not cfg.get("enabled", False):
            continue

        strategy = cfg.get("strategy", "sma_trend")
        sma_params = cfg.get("sma_params", {})
        fast = sma_params.get("fast", "?")
        slow = sma_params.get("slow", "?")

        # Find the most recent verdict file for this symbol
        verdict_info = _find_verdict(sym)

        entry: dict[str, Any] = {
            "symbol": sym,
            "strategy": strategy,
            "fast": fast,
            "slow": slow,
        }
        entry.update(verdict_info)
        active.append(entry)

    return active


def _find_verdict(symbol: str) -> dict[str, Any]:
    """Scan gate_v2_verdicts dir for the latest PASS verdict for this symbol."""
    default: dict[str, Any] = {
        "verdict_file": None,
        "verdict": "UNKNOWN",
        "passed_via": None,
        "created_at": None,
        "days_since_created": None,
        "days_until_expiry": None,
    }
    if not _GATE_V2_DIR.exists():
        return default

    now = datetime.now(_UTC)
    best: dict[str, Any] | None = None
    best_ts: datetime | None = None

    for fp in _GATE_V2_DIR.glob(f"{symbol.upper()}_*.json"):
        try:
            raw = fp.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("verdict") != "PASS":
            continue

        created_str = data.get("created_at", "")
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        if best_ts is None or created_dt > best_ts:
            best = data
            best_ts = created_dt
            best_fp = fp

    if best is None or best_ts is None:
        return default

    delta_days = (now - best_ts).days
    expiry_days = _VERDICT_TTL_DAYS - delta_days

    return {
        "verdict_file": best_fp.name,
        "verdict": best.get("verdict", "UNKNOWN"),
        "passed_via": best.get("passed_via"),
        "created_at": best_ts.strftime("%Y-%m-%d"),
        "days_since_created": delta_days,
        "days_until_expiry": expiry_days,
    }


def render_active_strategies(strategies: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("## 2. Active Strategies Today")
    if not strategies:
        lines.append("*No enabled strategies found in paper_config.*")
        lines.append("")
        return lines

    lines.append("| Symbol | Strategy | Params | Verdict | Via | Created | Expires In |")
    lines.append("|--------|----------|--------|---------|-----|---------|------------|")
    for s in strategies:
        sym = s["symbol"]
        strat = s.get("strategy", "?")
        params = f"SMA({s.get('fast', '?')},{s.get('slow', '?')})"
        verdict = s.get("verdict", "?")
        via = s.get("passed_via") or "—"
        created = s.get("created_at") or "—"
        expires = s.get("days_until_expiry")
        expires_str = f"{expires}d" if expires is not None else "—"
        lines.append(
            f"| {sym} | {strat} | {params} | **{verdict}** | {via} | {created} | {expires_str} |"
        )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section C — Overnight Bar Regime
# ---------------------------------------------------------------------------


def compute_overnight_regime(symbols: list[str], db_path: Path | None = None) -> dict[str, dict]:
    """
    For each symbol, load recent bars and compute regime/bias state.
    Returns {symbol: regime_dict}.
    """
    try:
        from analytics.regime import compute_bar_regime, load_recent_bars
    except ImportError:
        logger.warning("analytics.regime not importable — regime section unavailable")
        return {
            sym: {
                "regime": "IMPORT_ERROR",
                "bias": "UNKNOWN",
                "close": None,
                "atr": None,
                "sma_fast": None,
                "sma_slow": None,
                "fast": 0,
                "slow": 0,
            }
            for sym in symbols
        }

    result = {}
    for sym in symbols:
        df = load_recent_bars(sym, n_bars=_SMA_LOOKBACK_BARS, db_path=db_path or _DB_PATH)
        result[sym] = compute_bar_regime(sym, df)
    return result


def render_overnight_regime(regime_map: dict[str, dict]) -> list[str]:
    lines: list[str] = []
    lines.append("## 3. Overnight Bar Regime")
    if not regime_map:
        lines.append("*No regime data available.*")
        lines.append("")
        return lines

    lines.append("| Symbol | Regime | Bias | Close | ATR | SMA Fast | SMA Slow |")
    lines.append("|--------|--------|------|-------|-----|----------|----------|")
    for sym in sorted(regime_map):
        r = regime_map[sym]
        regime = r.get("regime", "?")
        bias = r.get("bias", "?")
        close = f"{r['close']:.2f}" if r.get("close") is not None else "—"
        atr = f"{r['atr']:.2f}" if r.get("atr") is not None else "—"
        sf = f"{r['sma_fast']:.2f}" if r.get("sma_fast") is not None else "—"
        ss = f"{r['sma_slow']:.2f}" if r.get("sma_slow") is not None else "—"
        lines.append(f"| {sym} | {regime} | {bias} | {close} | {atr} | {sf} | {ss} |")
    lines.append("")
    return lines


_RV_ACTIVATION_GATE = 60  # trades required before RV filter can be enabled
_RV_SYMBOLS = ("MES", "MGC")  # symbols with validated RV filter thresholds


def fetch_rv_accumulation(db_path: Path | None = None) -> dict[str, int]:
    """
    Return {symbol: rv_tagged_count} — count of paper_trades rows where
    strategy_params.rv_at_entry IS NOT NULL, per symbol.
    """
    path = db_path or _DB_PATH
    if not path.exists():
        return dict.fromkeys(_RV_SYMBOLS, 0)
    try:
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute(
                """
                SELECT symbol,
                       SUM(CASE WHEN json_extract(strategy_params, '$.rv_at_entry')
                                     IS NOT NULL THEN 1 ELSE 0 END) AS tagged
                FROM paper_trades
                WHERE symbol IN ('MES', 'MGC')
                GROUP BY symbol
                """
            ).fetchall()
        finally:
            conn.close()
        result = dict.fromkeys(_RV_SYMBOLS, 0)
        for sym, tagged in rows:
            if sym in result:
                result[sym] = int(tagged or 0)
        return result
    except Exception as exc:
        logger.warning("fetch_rv_accumulation failed: %s", exc)
        return dict.fromkeys(_RV_SYMBOLS, 0)


def render_rv_accumulation(rv_counts: dict[str, int] | None = None) -> list[str]:
    """Render RV filter calibration progress toward the 60-trade activation gate."""
    if rv_counts is None:
        rv_counts = fetch_rv_accumulation()

    lines: list[str] = []
    lines.append("### RV Filter Calibration Progress")
    lines.append(f"*(activation gate: {_RV_ACTIVATION_GATE} tagged trades per symbol)*")
    lines.append("")
    lines.append("| Symbol | Tagged | Progress | Status |")
    lines.append("|--------|--------|----------|--------|")
    for sym in _RV_SYMBOLS:
        count = rv_counts.get(sym, 0)
        filled = min(count, _RV_ACTIVATION_GATE)
        bar_len = 10
        n_filled = round(filled / _RV_ACTIVATION_GATE * bar_len)
        bar = "█" * n_filled + "░" * (bar_len - n_filled)
        pct = round(count / _RV_ACTIVATION_GATE * 100)
        if count >= _RV_ACTIVATION_GATE:
            status = "**READY TO EVALUATE**"
        else:
            status = f"not ready ({pct}%)"
        lines.append(f"| {sym} | {count}/{_RV_ACTIVATION_GATE} | `{bar}` | {status} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section D — Discord Overnight Signal
# ---------------------------------------------------------------------------


def fetch_discord_overnight(
    hours_back: int = _OVERNIGHT_HOURS,
    limit: int = 20,
    db_path: Path | None = None,
    timeout_s: float = 5.0,
) -> list[dict[str, str]]:
    """
    Pull the last *hours_back* hours of entries from discord_corey_commentary.
    Returns list of {timestamp, content} dicts (up to *limit*).
    Gracefully returns [] if DB unavailable or table missing.
    """
    path = db_path or _DB_PATH
    if not path.exists():
        return []

    cutoff = datetime.now(_UTC) - timedelta(hours=hours_back)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        con = sqlite3.connect(str(path), timeout=timeout_s)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='discord_corey_commentary'"
        )
        if not cur.fetchone():
            con.close()
            return []

        rows = con.execute(
            """
            SELECT timestamp, content
            FROM discord_corey_commentary
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (cutoff_iso, limit),
        ).fetchall()
        con.close()

        return [{"timestamp": r[0], "content": r[1]} for r in rows]
    except Exception as exc:
        logger.warning("discord_corey_commentary fetch failed (non-fatal): %s", exc)
        return []


def render_discord_overnight(entries: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    lines.append("## 4. Discord Overnight Signal (last 16h)")
    if not entries:
        lines.append("*No Corey commentary in the overnight window — DB empty or table missing.*")
        lines.append("")
        return lines

    lines.append(f"*{len(entries)} message(s) found. Most recent first:*")
    lines.append("")
    for entry in entries[:10]:  # cap at 10 in the rendered report
        ts = entry.get("timestamp", "")
        content = entry.get("content", "").strip()
        # Truncate long messages
        if len(content) > 200:
            content = content[:197] + "..."
        lines.append(f"- **{ts[:16]}** — {content}")
    if len(entries) > 10:
        lines.append(f"- *...{len(entries) - 10} more message(s) not shown*")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section E — Calendar / Events (placeholder)
# ---------------------------------------------------------------------------


def render_calendar_placeholder() -> list[str]:
    return [
        "## 5. Calendar / Events",
        "*No calendar source wired in v1. Future: pull from Google Calendar or Econoday.*",
        "",
    ]


# ---------------------------------------------------------------------------
# Section F — Strategy Expectations
# ---------------------------------------------------------------------------


def compute_strategy_expectations(
    active_strategies: list[dict[str, Any]],
    regime_map: dict[str, dict],
) -> list[dict[str, Any]]:
    """
    For each active strategy, compute SMA spread and whether a crossover
    is near (within 0.5% of price).
    """
    result: list[dict[str, Any]] = []
    for strat in active_strategies:
        sym = strat["symbol"]
        r = regime_map.get(sym, {})
        sma_f = r.get("sma_fast")
        sma_s = r.get("sma_slow")
        close = r.get("close")
        regime = r.get("regime", "UNKNOWN")
        bias = r.get("bias", "UNKNOWN")

        spread_pct: float | None = None
        crossover_proximity: str = "UNKNOWN"

        if sma_f is not None and sma_s is not None and sma_s > 0 and close is not None:
            spread_pct = (sma_f - sma_s) / sma_s * 100.0
            # Crossover proximity: how close is fast SMA to slow SMA as % of price
            gap_pct = abs(sma_f - sma_s) / close * 100.0
            if gap_pct < 0.3:
                crossover_proximity = "NEAR_CROSSOVER"
            elif gap_pct < 1.0:
                crossover_proximity = "APPROACHING"
            else:
                crossover_proximity = "DISTANT"

        result.append(
            {
                "symbol": sym,
                "fast": strat.get("fast", "?"),
                "slow": strat.get("slow", "?"),
                "regime": regime,
                "bias": bias,
                "spread_pct": spread_pct,
                "crossover_proximity": crossover_proximity,
                "sma_fast": sma_f,
                "sma_slow": sma_s,
            }
        )
    return result


def render_strategy_expectations(expectations: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("## 6. Strategy Expectations Today")
    if not expectations:
        lines.append("*No active strategies.*")
        lines.append("")
        return lines

    for exp in expectations:
        sym = exp["symbol"]
        lines.append(f"### {sym} — SMA({exp['fast']},{exp['slow']})")
        lines.append(f"- Regime: **{exp['regime']}**  |  Bias: **{exp['bias']}**")
        sp = exp.get("spread_pct")
        if sp is not None:
            direction = "above" if sp > 0 else "below"
            lines.append(f"- Fast SMA is **{abs(sp):.3f}%** {direction} slow SMA")
            lines.append(f"- Crossover proximity: **{exp['crossover_proximity']}**")
            if exp.get("sma_fast") and exp.get("sma_slow"):
                lines.append(
                    f"- SMA values: fast={exp['sma_fast']:.2f}  slow={exp['sma_slow']:.2f}"
                )
        else:
            lines.append("- SMA data unavailable (insufficient bars or import error)")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section G — Yesterday's Tally
# ---------------------------------------------------------------------------


def render_yesterday_tally(briefing_date: date) -> list[str]:
    yesterday = briefing_date - timedelta(days=1)
    report_path = _POST_TRADE_DIR / f"{yesterday.isoformat()}.md"
    lines: list[str] = []
    lines.append("## 7. Yesterday's Tally")
    if report_path.exists():
        rel = report_path.relative_to(_ENGINE_DIR)
        lines.append(f"Post-trade report: `{rel}`")
    else:
        lines.append(f"*No post-trade report found for {yesterday.isoformat()}.*")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section H — Open Positions
# ---------------------------------------------------------------------------


def fetch_open_positions(timeout: int = _HTTP_TIMEOUT_S) -> list[dict[str, Any]]:
    """
    Query /brokers/positions. Returns [] on failure or empty result.
    """
    try:
        with urlopen(_ENGINE_POSITIONS_URL, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("positions", []) or []
        return []
    except Exception as exc:
        logger.debug("fetch_open_positions failed: %s", exc)
        return []


def render_open_positions(positions: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append("## 8. Open Positions at Session Start")
    if not positions:
        lines.append("*No open positions (or /brokers/positions unreachable).*")
        lines.append("")
        return lines

    lines.append("| Symbol | Side | Qty | Entry | Unrealized |")
    lines.append("|--------|------|-----|-------|------------|")
    for p in positions:
        sym = p.get("symbol", "?")
        side = p.get("side") or p.get("action", "?")
        qty = p.get("quantity", "?")
        entry = p.get("entry_price") or p.get("avg_cost", "?")
        unrealized = p.get("unrealized_pnl")
        entry_str = f"{float(entry):.2f}" if entry not in (None, "?") else "?"
        unr_str = f"${float(unrealized):+.2f}" if unrealized is not None else "—"
        lines.append(f"| {sym} | {side} | {qty} | {entry_str} | {unr_str} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Section I — Attention Required
# ---------------------------------------------------------------------------


def compute_attention_items(
    health: dict[str, Any],
    active_strategies: list[dict[str, Any]],
    regime_map: dict[str, dict],
    briefing_date: date,
) -> list[str]:
    """
    Surface actionable items that require Amo's attention.
    Returns a list of plain-text issue strings.
    """
    items: list[str] = []

    # 1. Engine health degraded
    status = health.get("status", "UNKNOWN")
    if status not in ("ok", "OK"):
        items.append(f"ENGINE DEGRADED — /health reports status={status!r}")

    if health.get("kill_switch_active"):
        items.append("KILL SWITCH ACTIVE — trading is halted until manually cleared")

    if health.get("llm_path_healthy") is False:
        items.append("LLM PATH UNHEALTHY — signal generation may be impaired")

    if health.get("tradingview_mcp_healthy") is False:
        items.append("TRADINGVIEW MCP UNHEALTHY — bar data may be stale")

    # 2. Verdict expiring within warning window
    for strat in active_strategies:
        sym = strat["symbol"]
        expiry = strat.get("days_until_expiry")
        if expiry is not None and expiry <= _VERDICT_WARN_DAYS:
            items.append(
                f"VERDICT EXPIRING SOON — {sym} gate v2 verdict expires in {expiry}d "
                f"(file: {strat.get('verdict_file', 'unknown')})"
            )

    # 3. DO_NOT_TRADE drift — check if any enabled strategy is in the blocked list
    try:
        from backtest.paper_config import PAPER_CONFIGS

        for sym, cfg in PAPER_CONFIGS.items():
            if cfg.get("enabled", False) and sym in DO_NOT_TRADE_SYMBOLS:
                items.append(
                    f"CONFIG DRIFT — {sym} is ENABLED in paper_config but is in DO_NOT_TRADE_SYMBOLS"
                )
    except ImportError:
        pass

    # 4. Missing bar data for active symbols
    for strat in active_strategies:
        sym = strat["symbol"]
        r = regime_map.get(sym, {})
        if r.get("regime") in ("UNKNOWN", "INSUFFICIENT_DATA", "IMPORT_ERROR"):
            items.append(
                f"BAR DATA ISSUE — {sym} regime could not be computed "
                f"(regime={r.get('regime', 'UNKNOWN')})"
            )

    return items


def render_attention_items(items: list[str]) -> list[str]:
    lines: list[str] = []
    lines.append("## 9. Attention Required")
    if not items:
        lines.append("*Nothing flagged — all systems nominal.*")
        lines.append("")
        return lines

    for item in items:
        lines.append(f"- **{item}**")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Report renderer — assembles all sections
# ---------------------------------------------------------------------------


def render_briefing(
    briefing_date: date,
    health: dict[str, Any],
    active_strategies: list[dict[str, Any]],
    regime_map: dict[str, dict],
    discord_entries: list[dict[str, str]],
    expectations: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    attention_items: list[str],
    levels_map: dict[str, Any] | None = None,
    read: dict[str, Any] | None = None,
    corey_compare: dict[str, Any] | None = None,
) -> str:
    now_et = datetime.now(_ET).strftime("%Y-%m-%dT%H:%M %Z")
    lines: list[str] = []

    lines.append(f"# JARVIS Morning Briefing — {briefing_date.isoformat()}")
    lines.append(f"*Generated {now_et}*")
    lines.append("")

    lines.extend(render_engine_status(health))
    lines.extend(render_key_levels(levels_map or {}))
    lines.extend(render_jarvis_read(read))
    # Phase F — dormant: render_corey_compare returns [] while Corey's feed is dry.
    from analysis.corey_compare import render_corey_compare

    lines.extend(render_corey_compare(corey_compare))
    lines.extend(render_active_strategies(active_strategies))
    lines.extend(render_overnight_regime(regime_map))
    lines.extend(render_rv_accumulation())
    lines.extend(render_discord_overnight(discord_entries))
    lines.extend(render_calendar_placeholder())
    lines.extend(render_strategy_expectations(expectations))
    lines.extend(render_yesterday_tally(briefing_date))
    lines.extend(render_open_positions(positions))
    lines.extend(render_attention_items(attention_items))

    lines.append("---")
    lines.append("*JARVIS morning briefing — paper trading validation period*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord headline post
# ---------------------------------------------------------------------------


async def _post_discord_headline(
    briefing_date: date,
    health: dict[str, Any],
    active_strategies: list[dict[str, Any]],
    attention_items: list[str],
    report_path: Path,
) -> None:
    """Post a one-line morning headline to Discord via discord_notifier."""
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("httpx not available — Discord post skipped")
        return

    webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set — Discord post skipped")
        return

    status = health.get("status", "UNKNOWN")
    n_active = len(active_strategies)
    n_attn = len(attention_items)
    syms = ", ".join(s["symbol"] for s in active_strategies) if active_strategies else "—"
    attn_flag = " ⚠️ ACTION NEEDED" if n_attn > 0 else ""

    content = (
        f"[JARVIS MORNING] {briefing_date} | engine={status} | "
        f"strategies={n_active} ({syms}) | attention={n_attn}{attn_flag} | "
        f"report={report_path.name}"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                webhook_url,
                json={"content": content, "username": "JARVIS"},
            )
            if resp.status_code in (200, 204):
                logger.info("Discord morning headline posted for %s", briefing_date)
            else:
                logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("Discord headline post failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS daily morning briefing")
    parser.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (default: today ET)",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Skip Discord headline post",
    )
    args = parser.parse_args()

    if args.date:
        try:
            briefing_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            sys.exit(1)
    else:
        briefing_date = datetime.now(_ET).date()

    # Refuse to generate a briefing for a future date
    today_et = datetime.now(_ET).date()
    if briefing_date > today_et:
        logger.error(
            "Cannot generate briefing for a future date (%s > %s).",
            briefing_date,
            today_et,
        )
        sys.exit(1)

    logger.info("Generating morning briefing for %s", briefing_date)

    # Assemble all data sections
    health = fetch_engine_health()
    active_strategies = load_active_strategies()

    # Active symbols for regime computation
    active_symbols = [s["symbol"] for s in active_strategies]
    regime_map = compute_overnight_regime(active_symbols) if active_symbols else {}

    discord_entries = fetch_discord_overnight()

    expectations = compute_strategy_expectations(active_strategies, regime_map)
    positions = fetch_open_positions()

    # Deterministic structural levels (ES/NQ/MGC) — also persisted to the
    # forecast journal so the evening scorer can grade them.
    levels_map = compute_key_levels()
    # JARVIS's Read — the labeled discretionary opinion (LLM, display/journal only).
    read = compute_jarvis_read(briefing_date, levels_map, regime_map)
    _persist_forecast(briefing_date, levels_map, read=read)
    # Phase F — JARVIS vs Corey (dormant until the Corey Discord feed returns).
    corey_compare = compute_corey_compare(briefing_date, read, levels_map)

    attention_items = compute_attention_items(
        health=health,
        active_strategies=active_strategies,
        regime_map=regime_map,
        briefing_date=briefing_date,
    )

    # Render
    report_md = render_briefing(
        briefing_date=briefing_date,
        health=health,
        active_strategies=active_strategies,
        regime_map=regime_map,
        discord_entries=discord_entries,
        expectations=expectations,
        positions=positions,
        attention_items=attention_items,
        levels_map=levels_map,
        read=read,
        corey_compare=corey_compare,
    )

    # Save
    _BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _BRIEFING_DIR / f"{briefing_date.isoformat()}.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Briefing saved → %s", report_path)

    # Discord
    if not args.no_discord:
        import asyncio

        asyncio.run(
            _post_discord_headline(
                briefing_date, health, active_strategies, attention_items, report_path
            )
        )
    else:
        logger.info("Discord post skipped (--no-discord)")

    # Print headline to stdout for cron log capture
    status = health.get("status", "UNKNOWN")
    n_active = len(active_strategies)
    n_attn = len(attention_items)
    print(
        f"[JARVIS MORNING] {briefing_date} | engine={status} | "
        f"strategies={n_active} | attention={n_attn}"
    )


if __name__ == "__main__":
    main()
