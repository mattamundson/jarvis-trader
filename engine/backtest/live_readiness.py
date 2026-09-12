#!/usr/bin/env python
"""Retired legacy Phase-1 readiness diagnostics.

The seven checks remain useful as paper-evidence diagnostics, but this module is
not a live-authorization gate. It always fails closed with exit code 2.
JARVIS-MIP-1.0 M10 evidence, explicit Tier 3 owner authorization, and the M11
canary/reconciliation contract are separate requirements.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"
VERDICT_TTL_DAYS = 30
ENGINE_HEALTH_URL = "http://127.0.0.1:8010/health"
ENGINE_TIMEOUT_SEC = 5

# Machine-readable go/no-go state file written on every run.
# Consumers (dashboard, alerts, cron scripts) read this instead of re-running checks.
DEFAULT_STATE_FILE = engine_root / "data" / "live_readiness_state.json"
RETIREMENT_REASON = (
    "Legacy Phase-1 readiness is diagnostic-only and cannot authorize live trading. "
    "JARVIS-MIP-1.0 M10 plus explicit Tier 3 owner authorization are required "
    "before an M11 canary."
)

# C1 thresholds
PAPER_MIN_DAYS = 30
PAPER_MIN_TRADES = 30
PAPER_MIN_PF = 1.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True  # if False, advisory-only
    fix: str | None = None


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse ISO 8601 to a UTC-aware datetime.

    Coerces naive timestamps to UTC so callers can safely compare with
    datetime.now(tz=timezone.utc). The PortfolioTracker JSONL store is the
    canonical example — most entries are TZ-aware, but a handful of older
    entries have date-only strings that parse as naive.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


_ENGINE_HEALTH_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_ENGINE_HEALTH_CACHE_TTL_SEC = 5.0


def _fetch_engine_health() -> dict[str, Any] | None:
    """Fetch engine /health with a 5s cache and retry-on-transient.

    The cache exists so C4 (engine health) and C5 (kill switch) consult the
    same response within a single run_all_checks() invocation. Without it,
    C4 can FAIL on a transient timeout while C5 succeeds on a retry, producing
    an inconsistent verdict where the gate reports kill_switch=false against
    an "unreachable" engine.

    Retries up to 3 attempts before caching a None result. Cold-start TCP
    handshake on Windows occasionally takes >5s (observed 2026-05-06); the
    retry loop turns flaky single-call timeouts into a benign extra second.
    """
    import time

    now = time.monotonic()
    if now - _ENGINE_HEALTH_CACHE["ts"] < _ENGINE_HEALTH_CACHE_TTL_SEC:
        return _ENGINE_HEALTH_CACHE["data"]

    data = None
    for attempt in range(3):
        try:
            with urlopen(ENGINE_HEALTH_URL, timeout=ENGINE_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except (URLError, HTTPError, json.JSONDecodeError, OSError):
            if attempt < 2:
                time.sleep(1.0)
            # else: fall through with data=None

    _ENGINE_HEALTH_CACHE["ts"] = now
    _ENGINE_HEALTH_CACHE["data"] = data
    return data


def _load_verdicts() -> list[dict[str, Any]]:
    rows = []
    if not VERDICTS_DIR.exists():
        return rows
    for path in sorted(VERDICTS_DIR.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
            if text.strip():
                v = json.loads(text)
                v["__file"] = path.name
                rows.append(v)
        except (json.JSONDecodeError, OSError):
            continue
    return rows


# Curated paper-trade store. The forward-test reads the SQLite paper_trades
# table — the source the live PortfolioTracker reloads from — NOT the raw
# append-only portfolio/trades.jsonl. The jsonl carries no status field, so it
# never reflects DB-layer curation (duplicate cancellation, contaminated-row
# voiding, phantom voids) and over-counts voided/duplicate positions as live
# (it reported a phantom MES "+$30,918 / 43 open" book on 2026-06-16 that the
# live engine did not hold). Reading the curated table with a genuine-status
# filter keeps forward-test stats in sync with reality.
PAPER_TRADES_DB_PATH = engine_root / "data" / "jarvis_trader.db"

# Legacy raw store — retained for reference / backward-compatible imports only;
# no longer the forward-test source (see PAPER_TRADES_DB_PATH above).
PAPER_TRADES_PATH = engine_root / "portfolio" / "trades.jsonl"

# Statuses that represent genuine, non-curated-out paper trades. Everything else
# (cancelled_duplicate, cancelled_contaminated, phantom, ...) is excluded so a
# voided or duplicate position can never inflate forward-test counts or P&L.
GENUINE_OPEN_STATUS = "open"
GENUINE_CLOSED_STATUS = "closed"


def _query_paper_trade_stats(symbol: str) -> dict[str, Any]:
    """Return paper-trade stats for one symbol from the curated paper_trades DB.

    Reads engine/data/jarvis_trader.db (the SQLite store the live
    PortfolioTracker reloads from), counting only genuine rows — status 'open'
    or 'closed'. Curated-out rows (cancelled_duplicate / cancelled_contaminated
    / phantom / ...) are excluded, so the forward-test never counts a voided or
    duplicate phantom position as live. This replaced the prior
    portfolio/trades.jsonl reader, which had no status field and therefore
    over-reported open positions and P&L by every uncancelled raw append.

    Opens the DB read-only so this validator can never mutate live trade state.

    Returns dict with:
      n_closed       — int, count of status='closed' trades
      n_open         — int, count of status='open' positions
      first_entry    — datetime|None, earliest entry_time across genuine rows
      last_entry     — datetime|None, latest entry_time
      days_elapsed   — int|None, days from first_entry to now
      forward_pf     — float|None, sum(wins) / |sum(losses)| over closed trades.
                       None when n_closed==0; inf when no losing trades.
      total_pnl      — float, sum of pnl across closed trades
      available      — bool, True if the DB exists, is readable, and the query
                       succeeded
    """
    stats = {
        "n_closed": 0,
        "n_open": 0,
        "first_entry": None,
        "last_entry": None,
        "days_elapsed": None,
        "forward_pf": None,
        "total_pnl": 0.0,
        "available": False,
    }
    if not PAPER_TRADES_DB_PATH.exists():
        return stats

    try:
        conn = sqlite3.connect(
            f"{PAPER_TRADES_DB_PATH.as_uri()}?mode=ro", uri=True, timeout=5.0
        )
    except sqlite3.Error:
        return stats
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT entry_time, exit_time, pnl, status FROM paper_trades "
            "WHERE symbol = ? AND status IN (?, ?)",
            (symbol, GENUINE_OPEN_STATUS, GENUINE_CLOSED_STATUS),
        ).fetchall()
    except sqlite3.Error:
        # Missing table / corrupt DB — fall through as "no curated store".
        return stats
    finally:
        conn.close()

    # Query succeeded: the curated store is available.
    stats["available"] = True

    wins = 0.0
    losses = 0.0
    entries = []
    for r in rows:
        entry_dt = _parse_iso(r["entry_time"])
        if entry_dt is not None:
            entries.append(entry_dt)
        if r["status"] == GENUINE_OPEN_STATUS:
            stats["n_open"] += 1
            continue
        # Closed trade
        if r["exit_time"] is None:
            continue
        stats["n_closed"] += 1
        pnl = r["pnl"]
        if pnl is None:
            continue
        stats["total_pnl"] += float(pnl)
        if pnl > 0:
            wins += float(pnl)
        elif pnl < 0:
            losses += abs(float(pnl))

    if entries:
        stats["first_entry"] = min(entries)
        stats["last_entry"] = max(entries)
        now = datetime.now(tz=timezone.utc)
        stats["days_elapsed"] = (now - stats["first_entry"]).days

    if stats["n_closed"] > 0:
        if losses == 0:
            stats["forward_pf"] = float("inf") if wins > 0 else 0.0
        else:
            stats["forward_pf"] = wins / losses

    return stats


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_c1_mes_paper_validation() -> CheckResult:
    """30 days elapsed AND >=30 closed paper trades AND forward-test PF >= 1.0 on MES.

    Authoritative source: the curated paper_trades table in jarvis_trader.db.
    Falls back to the verdict-creation-date proxy when the curated store is
    missing/empty, which is the case before any paper trades have been recorded.
    """
    try:
        from backtest.paper_config import MES_TREND_PAPER_CONFIG
    except ImportError as e:
        return CheckResult(
            name="C1 MES paper validation",
            passed=False,
            detail=f"Cannot import MES_TREND_PAPER_CONFIG: {e}",
            fix="Verify engine/backtest/paper_config.py imports correctly",
        )

    if not MES_TREND_PAPER_CONFIG.get("enabled", False):
        return CheckResult(
            name="C1 MES paper validation",
            passed=False,
            detail="MES_TREND_PAPER_CONFIG.enabled=False",
            fix="Enable MES paper config after gate v2 verdict",
        )

    stats = _query_paper_trade_stats("MES")

    # If no paper trade store yet, fall back to verdict-date proxy. This handles
    # the bootstrap case before any trades have been recorded.
    if not stats["available"] or stats["first_entry"] is None:
        verdict_path = VERDICTS_DIR / "MES_trend_rank11.json"
        if not verdict_path.exists():
            return CheckResult(
                name="C1 MES paper validation",
                passed=False,
                detail="No paper trades recorded and MES_trend_rank11.json verdict missing",
                fix="Run run_mes_trend_rank11.py and start paper trading on MES",
            )
        try:
            v = json.loads(verdict_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return CheckResult(
                name="C1 MES paper validation",
                passed=False,
                detail=f"Cannot parse MES verdict: {e}",
            )
        created = _parse_iso(v.get("created_at"))
        if not created:
            return CheckResult(
                name="C1 MES paper validation",
                passed=False,
                detail="MES verdict missing created_at; no paper trades to fall back to",
            )
        days_elapsed = (datetime.now(tz=timezone.utc) - created).days
        return CheckResult(
            name="C1 MES paper validation",
            passed=False,
            detail=(
                f"No MES paper trades recorded yet; using verdict-date proxy "
                f"(day {days_elapsed} of {PAPER_MIN_DAYS}). Verify IB Gateway is "
                f"connected and engine routing is firing MES signals."
            ),
            fix=(
                f"Bring IB Gateway paper online; wait until "
                f"{(created + timedelta(days=PAPER_MIN_DAYS)).date()} for verdict-date "
                f"proxy expiry, OR until 30 trades fire."
            ),
        )

    # Real path: we have actual paper trade data
    days_elapsed = stats["days_elapsed"]
    n_closed = stats["n_closed"]
    forward_pf = stats["forward_pf"]

    failures = []
    if days_elapsed < PAPER_MIN_DAYS:
        failures.append(f"days={days_elapsed}<{PAPER_MIN_DAYS}")
    if n_closed < PAPER_MIN_TRADES:
        failures.append(f"closed_trades={n_closed}<{PAPER_MIN_TRADES}")
    if forward_pf is not None and forward_pf < PAPER_MIN_PF:
        failures.append(f"forward_pf={forward_pf:.3f}<{PAPER_MIN_PF}")

    pf_str = (
        f"{forward_pf:.3f}"
        if forward_pf not in (None, float("inf"))
        else ("inf" if forward_pf == float("inf") else "n/a")
    )
    detail = (
        f"days={days_elapsed}, closed={n_closed}, open={stats['n_open']}, "
        f"forward_pf={pf_str}, total_pnl=${stats['total_pnl']:.2f}"
    )

    if failures:
        return CheckResult(
            name="C1 MES paper validation",
            passed=False,
            detail=f"FAIL: {', '.join(failures)} | {detail}",
            fix=(
                f"Continue paper trading until thresholds met: "
                f">={PAPER_MIN_DAYS} days, >={PAPER_MIN_TRADES} closed trades, "
                f"forward_pf>={PAPER_MIN_PF}"
            ),
        )

    return CheckResult(
        name="C1 MES paper validation",
        passed=True,
        detail=f"PASS | {detail}",
    )


def check_c2_second_symbol() -> CheckResult:
    """At least one additional gate v2 PASS beyond MES."""
    verdicts = _load_verdicts()
    pass_symbols = set()
    for v in verdicts:
        if v.get("verdict") == "PASS":
            sym = v.get("symbol")
            if sym:
                pass_symbols.add(sym)

    non_mes_passes = pass_symbols - {"MES"}
    if not non_mes_passes:
        return CheckResult(
            name="C2 Second symbol validated",
            passed=False,
            detail=f"No PASS verdicts beyond MES. Found: {sorted(pass_symbols)}",
            fix="Need at least one of: MGC PASS, M2K PASS, or new symbol",
        )

    return CheckResult(
        name="C2 Second symbol validated",
        passed=True,
        detail=f"PASS symbols: {sorted(pass_symbols)} (non-MES: {sorted(non_mes_passes)})",
    )


def check_c3_phase0_complete() -> CheckResult:
    """Credential scanner returns 0 HIGH findings."""
    # Phase 0 status is tracked in user-level memory, not codebase. Best-effort
    # check: look for the rotation playbook + most recent scan output.
    scan_log = Path.home() / ".claude" / "logs" / "scan-credentials-latest.json"
    if not scan_log.exists():
        return CheckResult(
            name="C3 Phase 0 credential rotation",
            passed=False,
            detail=f"No scan-credentials output found at {scan_log}",
            fix="Run ~/scripts/scan-credentials.ps1 and save output to ~/.claude/logs/scan-credentials-latest.json",
            blocking=False,  # advisory until scan integration completes
        )

    try:
        # PowerShell's Set-Content -Encoding UTF8 writes a BOM. Use utf-8-sig
        # so the BOM is silently consumed; falls back gracefully on non-BOM
        # files since utf-8-sig accepts plain utf-8 too.
        scan = json.loads(scan_log.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as e:
        return CheckResult(
            name="C3 Phase 0 credential rotation",
            passed=False,
            detail=f"Cannot parse scan log: {e}",
            blocking=False,
        )

    # Two supported formats:
    #   - Summary dict: {"n_high": N, ...}
    #   - Findings array: [{"severity": "HIGH" | "MEDIUM", ...}, ...]
    # The latter is the native output of ~/scripts/scan-credentials.ps1.
    if isinstance(scan, list):
        n_high = sum(
            1 for f in scan if isinstance(f, dict) and str(f.get("severity", "")).upper() == "HIGH"
        )
    elif isinstance(scan, dict):
        n_high = scan.get("n_high", -1)
        if n_high == -1 and "findings" in scan and isinstance(scan["findings"], list):
            n_high = sum(
                1
                for f in scan["findings"]
                if isinstance(f, dict) and str(f.get("severity", "")).upper() == "HIGH"
            )
    else:
        return CheckResult(
            name="C3 Phase 0 credential rotation",
            passed=False,
            detail="Scan log format not recognized (expected list or dict)",
            blocking=False,
        )

    if n_high == 0:
        return CheckResult(
            name="C3 Phase 0 credential rotation",
            passed=True,
            detail="0 HIGH findings",
        )
    return CheckResult(
        name="C3 Phase 0 credential rotation",
        passed=False,
        detail=f"{n_high} HIGH findings remain",
        fix="Complete Phase 0 rotation per ~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md",
    )


def check_c4_engine_health() -> CheckResult:
    """status=ok + tv_mcp_healthy=true + llm_path_healthy=true."""
    health = _fetch_engine_health()
    if health is None:
        return CheckResult(
            name="C4 Engine health",
            passed=False,
            detail=f"Engine unreachable at {ENGINE_HEALTH_URL}",
            fix="Run .\\restart_engine.ps1 from jarvis-trader root",
        )

    failures = []
    if health.get("status") != "ok":
        failures.append(f"status={health.get('status')}")
    if not health.get("tv_mcp_status") == "healthy" and not health.get("tradingview_mcp_healthy"):
        failures.append("tv_mcp not healthy")
    if not health.get("llm_path_healthy"):
        failures.append("llm_path not healthy")

    if failures:
        return CheckResult(
            name="C4 Engine health",
            passed=False,
            detail=f"Health failures: {', '.join(failures)}",
            fix="Diagnose with: curl http://127.0.0.1:8010/health | jq",
        )

    return CheckResult(
        name="C4 Engine health",
        passed=True,
        detail=f"status=ok, tv_mcp+llm_path healthy (uptime={health.get('uptime_seconds', 0):.0f}s)",
    )


def check_c5_kill_switch_inactive() -> CheckResult:
    """kill_switch_active=false."""
    health = _fetch_engine_health()
    if health is None:
        return CheckResult(
            name="C5 Kill switch INACTIVE",
            passed=False,
            detail="Engine unreachable; cannot verify kill switch state",
            fix="Bring engine up first (C4)",
        )

    if health.get("kill_switch_active", True):  # default to True (safe) if missing
        return CheckResult(
            name="C5 Kill switch INACTIVE",
            passed=False,
            detail="kill_switch_active=true — system is in halted state",
            fix="Investigate why kill switch fired; clear via /admin/clear-kill-switch only after root cause identified",
        )

    return CheckResult(
        name="C5 Kill switch INACTIVE",
        passed=True,
        detail="kill_switch_active=false",
    )


def check_c6_verdicts_current() -> CheckResult:
    """Every PASS verdict in gate_v2_verdicts/ created within VERDICT_TTL_DAYS."""
    verdicts = _load_verdicts()
    pass_verdicts = [v for v in verdicts if v.get("verdict") == "PASS"]

    if not pass_verdicts:
        return CheckResult(
            name="C6 All verdicts current",
            passed=False,
            detail="No PASS verdicts found",
            fix="Run WFO campaigns until at least one strategy PASSes gate v2",
        )

    now = datetime.now(tz=timezone.utc)
    expired = []
    expiring_soon = []
    for v in pass_verdicts:
        created = _parse_iso(v.get("created_at"))
        if not created:
            continue
        age_days = (now - created).days
        if age_days >= VERDICT_TTL_DAYS:
            expired.append(f"{v.get('__file')} ({age_days}d old)")
        elif age_days >= VERDICT_TTL_DAYS - 7:
            expiring_soon.append(f"{v.get('__file')} ({VERDICT_TTL_DAYS - age_days}d remaining)")

    if expired:
        return CheckResult(
            name="C6 All verdicts current",
            passed=False,
            detail=f"Expired verdicts: {', '.join(expired)}",
            fix="Refresh expired verdicts by re-running their WFO runners with extended IBKR data",
        )

    detail = f"{len(pass_verdicts)} PASS verdicts, all within {VERDICT_TTL_DAYS}-day window"
    if expiring_soon:
        detail += f" — EXPIRING SOON: {', '.join(expiring_soon)}"

    return CheckResult(
        name="C6 All verdicts current",
        passed=True,
        detail=detail,
    )


def check_c7_do_not_trade_symbols() -> CheckResult:
    """All FAIL-only symbols are blocked; all PASS symbols are NOT blocked."""
    try:
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
    except ImportError as e:
        return CheckResult(
            name="C7 DO_NOT_TRADE_SYMBOLS sync",
            passed=False,
            detail=f"Cannot import DO_NOT_TRADE_SYMBOLS: {e}",
        )

    verdicts = _load_verdicts()
    by_symbol: dict[str, list[str]] = {}
    for v in verdicts:
        sym = v.get("symbol")
        verdict = v.get("verdict", "?")
        if sym:
            by_symbol.setdefault(sym, []).append(verdict)

    issues = []
    for sym, verdict_list in by_symbol.items():
        has_pass = "PASS" in verdict_list
        has_fail = "FAIL" in verdict_list
        if has_pass and sym in DO_NOT_TRADE_SYMBOLS:
            issues.append(f"{sym}: has PASS verdict but is in DO_NOT_TRADE_SYMBOLS")
        if not has_pass and has_fail and sym not in DO_NOT_TRADE_SYMBOLS:
            issues.append(f"{sym}: only FAIL verdicts, not in DO_NOT_TRADE_SYMBOLS")

    if issues:
        return CheckResult(
            name="C7 DO_NOT_TRADE_SYMBOLS sync",
            passed=False,
            detail=f"Inconsistencies: {'; '.join(issues)}",
            fix="Edit engine/backtest/signals.py:DO_NOT_TRADE_SYMBOLS to match verdict state",
        )

    return CheckResult(
        name="C7 DO_NOT_TRADE_SYMBOLS sync",
        passed=True,
        detail=f"DO_NOT_TRADE_SYMBOLS={set(DO_NOT_TRADE_SYMBOLS)} matches verdict state",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CHECKS = [
    check_c1_mes_paper_validation,
    check_c2_second_symbol,
    check_c3_phase0_complete,
    check_c4_engine_health,
    check_c5_kill_switch_inactive,
    check_c6_verdicts_current,
    check_c7_do_not_trade_symbols,
]


def run_all_checks() -> list[CheckResult]:
    return [check() for check in CHECKS]


def _print_table(results: list[CheckResult]) -> None:
    print()
    print("=" * 80)
    print("RETIRED LEGACY READINESS DIAGNOSTICS — NO LIVE AUTHORIZATION")
    print("=" * 80)
    n_pass_blocking = 0
    n_blocking = 0
    for r in results:
        marker = "PASS" if r.passed else ("FAIL" if r.blocking else "WARN")
        print(f"\n[{marker}] {r.name}")
        print(f"       {r.detail}")
        if not r.passed and r.fix:
            print(f"  FIX: {r.fix}")
        if r.blocking:
            n_blocking += 1
            if r.passed:
                n_pass_blocking += 1
    print()
    print("=" * 80)
    print(f"BLOCKING CHECKS: {n_pass_blocking}/{n_blocking} PASS")
    print("VERDICT: RETIRED / LIVE TRADING BLOCKED")
    print(f"REASON: {RETIREMENT_REASON}")
    print("=" * 80)
    print()


def _write_state_file(
    path: Path,
    results: list[CheckResult],
    exit_code: int,
    *,
    error: str | None = None,
) -> None:
    """Write machine-readable go/no-go state to disk.

    Consumers (dashboard, scheduled alerts, cron scripts) can read this file
    without re-running the full checks. The file is written atomically via a
    temp file + rename to avoid partial reads.
    """
    blocking_pass = sum(1 for r in results if r.passed and r.blocking)
    blocking_total = sum(1 for r in results if r.blocking)
    payload: dict[str, Any] = {
        "authorized": False,
        "legacy_criteria_pass": blocking_pass == blocking_total and not error,
        "retired": True,
        "authorization_reason": RETIREMENT_REASON,
        "blocking_pass": blocking_pass,
        "blocking_total": blocking_total,
        "exit_code": 2,
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
    }
    if error:
        payload["error"] = error

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _run_once(args: Any, state_path: Path | None) -> tuple[list[CheckResult], int]:
    """Run all checks once; return (results, exit_code)."""
    try:
        results = run_all_checks()
    except Exception as exc:
        err_msg = str(exc)
        if args.json:
            print(json.dumps({"error": err_msg, "exit_code": 2}))
        else:
            print(f"ERROR: live-readiness check infrastructure failed: {exc}")
        if state_path:
            _write_state_file(state_path, [], 2, error=err_msg)
        return [], 2

    if args.strict:
        for r in results:
            r.blocking = True

    # Criteria are retained as diagnostics, but this retired gate never authorizes.
    return results, 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of formatted table")
    parser.add_argument(
        "--strict", action="store_true", help="Treat advisory checks (C3) as blocking"
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help=(
            "Path to write machine-readable go/no-go state JSON " f"(default: {DEFAULT_STATE_FILE})"
        ),
    )
    parser.add_argument(
        "--no-state-file",
        action="store_true",
        help="Skip writing the state file (stdout only)",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help=(
            "Hands-off monitor mode: run checks on a repeating interval, print "
            "full table on first run and on any status change, print one-line "
            "heartbeat otherwise. Use with --interval to set cadence."
        ),
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        metavar="SECONDS",
        help="Seconds between checks in --monitor mode (default: 3600 = 1 hour).",
    )
    args = parser.parse_args()

    state_path = Path(args.state_file) if not args.no_state_file else None

    # ── Single-run mode (default) ────────────────────────────────────────────
    if not args.monitor:
        results, exit_code = _run_once(args, state_path)
        if not results and exit_code == 2:
            return 2

        if args.json:
            print(
                json.dumps(
                    {
                        "results": [asdict(r) for r in results],
                        "blocking_pass": sum(1 for r in results if r.passed and r.blocking),
                        "blocking_total": sum(1 for r in results if r.blocking),
                        "authorized": False,
                        "retired": True,
                        "authorization_reason": RETIREMENT_REASON,
                    },
                    indent=2,
                )
            )
        else:
            _print_table(results)

        if state_path:
            _write_state_file(state_path, results, exit_code)

        return exit_code

    # ── Monitor mode: loop until Ctrl-C ─────────────────────────────────────
    import time

    print(
        f"[monitor] Starting live-readiness monitor (interval={args.interval}s). " "Ctrl-C to stop."
    )
    prev_pass_map: dict[str, bool] = {}  # criterion_name → passed
    iteration = 0

    while True:
        now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        results, exit_code = _run_once(args, state_path)

        if not results and exit_code == 2:
            print(f"[monitor] {now_str} -- ERROR: checks failed; retrying in {args.interval}s")
        else:
            # Detect transitions
            curr_pass_map = {r.name: r.passed for r in results}
            changed = {
                name: (prev_pass_map[name], curr_pass_map[name])
                for name in curr_pass_map
                if name in prev_pass_map and prev_pass_map[name] != curr_pass_map[name]
            }

            status_str = "RETIRED/BLOCKED"
            blocking_fail = sum(1 for r in results if not r.passed and r.blocking)

            if iteration == 0 or changed:
                # First run or status change: print full table
                if changed:
                    print(f"\n[monitor] {now_str} -- STATUS CHANGE DETECTED:")
                    for name, (was, _now_val) in changed.items():
                        direction = "PASS→FAIL" if was else "FAIL→PASS"
                        symbol = "⚠" if was else "✓"
                        print(f"  {symbol} {name}: {direction}")
                    print()
                _print_table(results)
                print(f"\n[{status_str}] {now_str} | blocking failures: {blocking_fail}")
            else:
                # Heartbeat: one-line summary only
                print(
                    f"[monitor] {now_str} | {status_str} | "
                    f"failures: {blocking_fail} | next: {args.interval}s"
                )

            if state_path:
                _write_state_file(state_path, results, exit_code)

            prev_pass_map = curr_pass_map

        iteration += 1

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[monitor] Stopped.")
            break

    return 2


if __name__ == "__main__":
    sys.exit(main())
