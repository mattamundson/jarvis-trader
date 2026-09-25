#!/usr/bin/env python3
"""
JARVIS alert bridge — state-change detector that emits operator alerts.

WHY THIS EXISTS
---------------
The engine can compute everything correctly and still leave the operator
unaware: a signal can fire, a stop can be hit, drawdown can cross a threshold,
or the gateway can drop — and none of it reaches you unless you happen to be
looking at the dashboard.

This bridge closes that loop. It reads the engine's REST surface, compares
against the last observed state, and emits an alert ONLY on a meaningful
CHANGE. State-change detection (rather than level detection) is deliberate: a
level-based alerter would scream every tick while drawdown sits above a
threshold and you would learn to ignore it.

WATCHED CONDITIONS
------------------
  new_signal        a symbol's action changed (or appeared) since last run
  signal_flip       direction reversed LONG<->SHORT
  kill_switch       kill switch activated / cleared
  gateway_loss      IB Gateway port stopped accepting connections
  gateway_restore   IB Gateway came back
  data_stale        market_data_fresh flipped true->false
  drawdown_warn     drawdown crossed the warn threshold upward
  trading_mode      paper/live mode changed
  engine_down       /health became unreachable
  engine_up         /health recovered

OUTPUT
------
Silent (exit 0, no stdout) when nothing changed — cron-safe.
Prints one line per alert when something did.

STATE
-----
Persisted to a JSON file beside this script so restarts do not re-alert.
stdlib only: a dependency break must never silence a safety alert.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ENGINE_HOST = os.environ.get("JARVIS_ENGINE_HOST", "127.0.0.1")
ENGINE_PORT = int(os.environ.get("JARVIS_ENGINE_PORT", "8010"))
IB_PORT = int(os.environ.get("JARVIS_IB_PORT", "4002"))
HTTP_TIMEOUT_S = float(os.environ.get("ALERT_HTTP_TIMEOUT", "8"))
DRAWDOWN_WARN_PCT = float(os.environ.get("ALERT_DRAWDOWN_WARN", "15"))
REPO_ROOT = os.environ.get(
    "JARVIS_REPO", r"C:\Users\mattm\ThinkorSwim\jarvis-trader"
)
STATE_PATH = os.environ.get(
    "ALERT_STATE_PATH",
    os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "hermes",
        "cache",
        "jarvis_alert_bridge_state.json",
    ),
)


def _read_api_key() -> str:
    key = os.environ.get("API_KEY", "").strip()
    if key:
        return key
    try:
        with open(
            os.path.join(REPO_ROOT, "engine", ".env"), encoding="utf-8", errors="replace"
        ) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


API_KEY = _read_api_key()


# ── probes ───────────────────────────────────────────────────────────────────


def engine_get(path: str) -> tuple[dict | None, str | None]:
    req = urllib.request.Request(f"http://{ENGINE_HOST}:{ENGINE_PORT}{path}")
    if API_KEY:
        req.add_header("X-API-Key", API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"unreachable: {exc.reason}"
    except (TimeoutError, socket.timeout):
        return None, "timeout"
    except json.JSONDecodeError as exc:
        return None, f"bad json: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def port_open(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((ENGINE_HOST, port))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        sock.close()


# ── state ────────────────────────────────────────────────────────────────────


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
    except OSError:
        pass


# ── snapshot ─────────────────────────────────────────────────────────────────


def take_snapshot() -> dict:
    """Read everything we watch. Every read degrades to None, never raises."""
    health, health_err = engine_get("/health")
    perf, _ = engine_get("/portfolio/paper/performance")
    signals, _ = engine_get("/pipeline/status")

    snap: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "engine_up": health is not None and health_err is None,
        "gateway_open": port_open(IB_PORT),
        "kill_switch": None,
        "trading_mode": None,
        "data_fresh": None,
        "drawdown_pct": None,
        "signals": {},
    }

    if health:
        snap["kill_switch"] = bool(health.get("kill_switch_active"))
        snap["trading_mode"] = "LIVE" if health.get("live_trading") else "PAPER"
        snap["data_fresh"] = bool(health.get("market_data_fresh"))

    if perf:
        perf_inner = perf.get("performance") or perf
        max_dd = perf_inner.get("max_dd")
        total_pnl = perf_inner.get("total_pnl")
        if max_dd is not None and total_pnl is not None:
            try:
                dd_dollars = abs(float(max_dd))
                pnl = float(total_pnl)
                starting = float(os.environ.get("JARVIS_STARTING_EQUITY", "10000"))
                equity = starting + pnl
                peak = equity + dd_dollars
                if peak > 0:
                    snap["drawdown_pct"] = round((dd_dollars / peak) * 100.0, 2)
            except (TypeError, ValueError):
                pass

    # Signals: map symbol -> action. Shape: {"last_run": {...}} or {"runs": [...]}
    if signals:
        last = signals.get("last_run") or {}
        if last.get("symbol"):
            snap["signals"][str(last["symbol"]).upper()] = str(last.get("action", "")).upper()
        for run in (signals.get("runs") or [])[:10]:
            if run.get("symbol"):
                snap["signals"].setdefault(
                    str(run["symbol"]).upper(), str(run.get("action", "")).upper()
                )

    return snap


# ── diff ─────────────────────────────────────────────────────────────────────


def diff(prev: dict, curr: dict) -> list[str]:
    """Return human-readable alert lines for meaningful changes only."""
    alerts: list[str] = []
    if not prev:
        return alerts  # first run establishes the baseline; never alerts

    # Engine liveness
    if prev.get("engine_up") and not curr.get("engine_up"):
        alerts.append("ENGINE DOWN — /health unreachable; positions are unsupervised")
    elif not prev.get("engine_up") and curr.get("engine_up"):
        alerts.append("ENGINE RECOVERED — /health responding again")

    # Gateway
    if prev.get("gateway_open") and not curr.get("gateway_open"):
        alerts.append(f"GATEWAY LOST — port {IB_PORT} stopped accepting connections")
    elif not prev.get("gateway_open") and curr.get("gateway_open"):
        alerts.append(f"GATEWAY RESTORED — port {IB_PORT} accepting connections")

    # Kill switch
    if prev.get("kill_switch") is not None and curr.get("kill_switch") is not None:
        if not prev["kill_switch"] and curr["kill_switch"]:
            alerts.append("KILL SWITCH ACTIVATED — trading halted")
        elif prev["kill_switch"] and not curr["kill_switch"]:
            alerts.append("KILL SWITCH CLEARED — trading resumed")

    # Trading mode
    if prev.get("trading_mode") and curr.get("trading_mode"):
        if prev["trading_mode"] != curr["trading_mode"]:
            alerts.append(
                f"TRADING MODE CHANGED — {prev['trading_mode']} -> {curr['trading_mode']}"
            )

    # Data freshness
    if prev.get("data_fresh") is True and curr.get("data_fresh") is False:
        alerts.append("MARKET DATA STALE — market_data_fresh flipped to false")

    # Drawdown crossing upward
    p_dd, c_dd = prev.get("drawdown_pct"), curr.get("drawdown_pct")
    if p_dd is not None and c_dd is not None:
        if p_dd < DRAWDOWN_WARN_PCT <= c_dd:
            alerts.append(
                f"DRAWDOWN WARN — {c_dd:.2f}% crossed the {DRAWDOWN_WARN_PCT:.0f}% "
                f"threshold (kill switch at 20%)"
            )

    # Signals
    p_sig, c_sig = prev.get("signals") or {}, curr.get("signals") or {}
    for symbol, action in c_sig.items():
        old = p_sig.get(symbol)
        if old is None:
            alerts.append(f"NEW SIGNAL — {symbol}: {action}")
        elif old != action:
            if {old, action} == {"LONG", "SHORT"}:
                alerts.append(f"SIGNAL FLIP — {symbol}: {old} -> {action}")
            else:
                alerts.append(f"SIGNAL CHANGE — {symbol}: {old} -> {action}")

    return alerts


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    prev = load_state()
    curr = take_snapshot()
    alerts = diff(prev, curr)

    # Always persist the new baseline, even when silent.
    save_state(curr)

    if not alerts:
        if "--verbose" in sys.argv:
            print("alert-bridge: no change")
            for k in ("engine_up", "gateway_open", "kill_switch", "trading_mode",
                      "data_fresh", "drawdown_pct"):
                print(f"  {k}: {curr.get(k)}")
        return 0

    stamp = datetime.now().strftime("%H:%M:%S")
    for line in alerts:
        print(f"[{stamp}] {line}")
    return 0  # informational, never a cron failure


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ALERT BRIDGE ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
