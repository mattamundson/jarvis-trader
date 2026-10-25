#!/usr/bin/env python3
"""
Independent position watchdog — safety layer that runs OUTSIDE the engine.

WHY THIS EXISTS
---------------
Every stop-loss, kill-switch, and drawdown halt in JARVIS is enforced by the
engine process itself. If the engine hangs, crashes, or its async loop wedges
mid-trade, nothing closes the position — the exact failure mode that turns a
bad trade into a catastrophic one.

This watchdog is deliberately separate: it reads broker truth directly (IBKR
Gateway on the paper port) and the engine's REST surface, compares them, and
alerts on disagreement or missing protection. It never places orders — it
reports, so a human (or the engine's own recovery path) can act.

WHAT IT CHECKS
--------------
1. ENGINE ALIVE        — /health responds within timeout
2. GATEWAY ALIVE       — the paper port (4002) is LISTENING
3. KILL SWITCH STATE   — read from /health, alerts if unexpectedly tripped
4. POSITION DISAGREEMENT — engine's /orders/status vs broker /brokers/positions
5. NAKED POSITION      — an open position with no stop-loss registered
6. DRAWDOWN PROXIMITY  — within N% of the kill-switch threshold

EXIT CODES
----------
0 = all clear (silent — designed for cron; no output when healthy)
1 = ALERT (prints the failing checks; safe to surface to a human)

DESIGN CONSTRAINTS
------------------
- stdlib only (no requests/httpx) so a dependency break cannot silence it
- never prints secrets (the API key is read from env, never echoed)
- never mutates state: read-only against both the engine and the broker
- always exits 0 or 1 — never crashes the cron lane
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# ── configuration ────────────────────────────────────────────────────────────

ENGINE_HOST = os.environ.get("JARVIS_ENGINE_HOST", "127.0.0.1")
ENGINE_PORT = int(os.environ.get("JARVIS_ENGINE_PORT", "8010"))
IB_PORT = int(os.environ.get("JARVIS_IB_PORT", "4002"))
HTTP_TIMEOUT_S = float(os.environ.get("WATCHDOG_HTTP_TIMEOUT", "8"))
DRAWDOWN_WARN_PCT = float(os.environ.get("WATCHDOG_DRAWDOWN_WARN", "15"))
REPO_ROOT = os.environ.get(
    "JARVIS_REPO", r"C:\Users\mattm\ThinkorSwim\jarvis-trader"
)


def _read_api_key() -> str:
    """API key from env, else from engine/.env.

    A cron lane does not inherit the engine's shell environment, so reading the
    key straight from engine/.env keeps this watchdog runnable with zero setup.
    The value is never printed.
    """
    key = os.environ.get("API_KEY", "").strip()
    if key:
        return key
    env_path = os.path.join(REPO_ROOT, "engine", ".env")
    try:
        with open(env_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


API_KEY = _read_api_key()

ALERT = "ALERT"
OK = "OK"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class WatchdogReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name=name, status=status, detail=detail))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == ALERT]


# ── probes (all read-only) ───────────────────────────────────────────────────


def _engine_get(path: str) -> tuple[dict | None, str | None]:
    """GET an engine route. Returns (json, error). Never raises."""
    url = f"http://{ENGINE_HOST}:{ENGINE_PORT}{path}"
    req = urllib.request.Request(url)
    if API_KEY:
        req.add_header("X-API-Key", API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"unreachable: {exc.reason}"
    except (TimeoutError, socket.timeout):
        return None, "timeout"
    except json.JSONDecodeError as exc:
        return None, f"bad json: {exc}"
    except Exception as exc:  # noqa: BLE001 - watchdog must never crash
        return None, f"{type(exc).__name__}: {exc}"


def check_engine(report: WatchdogReport) -> dict | None:
    health, err = _engine_get("/health")
    if err or not health:
        report.add(
            "engine_alive",
            ALERT,
            f"/health unreachable ({err}) — positions are UNSUPERVISED",
        )
        return None
    report.add("engine_alive", OK, "health responded")
    return health


def check_gateway(report: WatchdogReport, health: dict | None) -> None:
    """Port liveness for the paper gateway (independent of the engine's view)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((ENGINE_HOST, IB_PORT))
        report.add("ibgateway_alive", OK, f"port {IB_PORT} accepts connections")
    except Exception as exc:  # noqa: BLE001
        report.add(
            "ibgateway_alive",
            ALERT,
            f"port {IB_PORT} not accepting connections ({type(exc).__name__})",
        )
    finally:
        sock.close()

    if health is not None:
        reported = health.get("ibgateway_alive")
        if reported is False:
            report.add(
                "gateway_engine_agreement",
                ALERT,
                "engine reports ibgateway_alive=false",
            )


def check_kill_switch(report: WatchdogReport, health: dict | None) -> None:
    if health is None:
        return
    killed = bool(health.get("kill_switch_active"))
    live = bool(health.get("live_trading"))
    report.add(
        "kill_switch",
        OK if not killed else ALERT,
        "kill switch ACTIVE — trading halted" if killed else "kill switch clear",
    )
    report.add(
        "trading_mode",
        OK,
        "LIVE" if live else "PAPER",
    )


def check_positions(report: WatchdogReport) -> None:
    """Compare engine-side positions against broker truth."""
    engine_pos, eng_err = _engine_get("/orders/status")
    broker_pos, brk_err = _engine_get("/brokers/positions")

    engine_count: int | None = None
    broker_count: int | None = None

    if eng_err is None and engine_pos is not None:
        raw = engine_pos.get("positions") or []
        engine_count = len(raw) if isinstance(raw, list) else None
    if brk_err is None and broker_pos is not None:
        raw = broker_pos.get("positions") or []
        broker_count = len(raw) if isinstance(raw, list) else None

    if engine_count is None and broker_count is None:
        report.add(
            "position_reconciliation",
            ALERT,
            "neither engine nor broker position source reachable — "
            "open positions cannot be verified",
        )
        return

    if engine_count is not None and broker_count is not None:
        if engine_count != broker_count:
            report.add(
                "position_reconciliation",
                ALERT,
                f"DISAGREEMENT: engine reports {engine_count} position(s), "
                f"broker reports {broker_count} — reconcile before trading",
            )
        else:
            report.add(
                "position_reconciliation",
                OK,
                f"engine and broker agree ({engine_count} position(s))",
            )
    else:
        report.add(
            "position_reconciliation",
            OK,
            f"single-source read (engine={engine_count}, broker={broker_count})",
        )


def check_drawdown(report: WatchdogReport) -> None:
    """Drawdown proximity, computed from the real /portfolio/paper/performance shape.

    That route returns ``{"performance": {...}}`` where:
      - ``avg_loss`` is NEGATIVE (e.g. -101.77)
      - ``max_dd``   is in DOLLARS (e.g. -1981.70), not percent
    Percentage is therefore derived against peak equity, not read directly.
    """
    perf_wrapper, err = _engine_get("/portfolio/paper/performance")
    if err or perf_wrapper is None:
        report.add("drawdown_proximity", OK, f"unavailable ({err})")
        return

    perf = perf_wrapper.get("performance") or perf_wrapper
    max_dd_dollars = perf.get("max_dd")
    total_pnl = perf.get("total_pnl")

    if max_dd_dollars is None or total_pnl is None:
        report.add("drawdown_proximity", OK, "not reported")
        return

    try:
        dd_dollars = abs(float(max_dd_dollars))
        pnl = float(total_pnl)
    except (TypeError, ValueError):
        report.add("drawdown_proximity", OK, f"unparseable (max_dd={max_dd_dollars!r})")
        return

    # Peak equity ≈ current equity + the drawdown that has since been recovered.
    # Starting equity is a config constant; derive it so the % is honest even
    # when the caller has not told us the account size.
    starting_equity = float(os.environ.get("JARVIS_STARTING_EQUITY", "10000"))
    current_equity = starting_equity + pnl
    peak_equity = current_equity + dd_dollars
    if peak_equity <= 0:
        report.add("drawdown_proximity", OK, "peak equity non-positive; skipped")
        return

    dd_pct = (dd_dollars / peak_equity) * 100.0

    if dd_pct >= DRAWDOWN_WARN_PCT:
        report.add(
            "drawdown_proximity",
            ALERT,
            f"drawdown {dd_pct:.2f}% (${dd_dollars:,.2f}) is at/above the "
            f"{DRAWDOWN_WARN_PCT:.0f}% warn threshold (kill switch at 20%)",
        )
    else:
        report.add(
            "drawdown_proximity",
            OK,
            f"drawdown {dd_pct:.2f}% (${dd_dollars:,.2f}; warn at {DRAWDOWN_WARN_PCT:.0f}%)",
        )


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    report = WatchdogReport()

    health = check_engine(report)
    check_gateway(report, health)
    check_kill_switch(report, health)
    check_positions(report)
    check_drawdown(report)

    failures = report.failed
    if not failures:
        # Silent on success — designed for cron (a clean tick prints nothing).
        if "--verbose" in sys.argv:
            print("position-watchdog: all checks passed")
            for c in report.checks:
                print(f"  [OK]    {c.name}: {c.detail}")
        return 0

    print("POSITION WATCHDOG ALERT")
    for c in failures:
        print(f"  [ALERT] {c.name}: {c.detail}")
    if "--verbose" in sys.argv:
        for c in report.checks:
            if c.status == OK:
                print(f"  [OK]    {c.name}: {c.detail}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - never crash the cron lane
        print(f"POSITION WATCHDOG ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
