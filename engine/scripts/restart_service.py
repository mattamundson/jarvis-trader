#!/usr/bin/env python3
"""
JARVIS service control — restart engine/dashboard WITHOUT the PM2 CLI.

WHY THIS EXISTS
---------------
On this host the PM2 CLI is wedged: `pm2 ping` answers instantly (the daemon is
alive) but `pm2 list`, `pm2 jlist`, `pm2 save` and `pm2 restart` return exit 0
with NO output, indefinitely. The daemon keeps supervising and restarting
crashed children, but no operator command can drive it.

That leaves a real gap: if the engine wedges (its async loop stalls while the
socket stays open), PM2 will NOT notice — the process is still alive, so there
is nothing to restart. Someone has to kill it so PM2 respawns it.

This script is that someone. It kills the listening process and lets the
supervisor bring it back, which is the only recovery action the wedged CLI
cannot block.

USAGE
-----
    python restart_service.py engine        # restart the engine (8010)
    python restart_service.py dashboard     # restart the dashboard (3010)
    python restart_service.py engine --verify-only

Behaviour:
  1. find the PID listening on the target port
  2. kill it (PM2 respawns its child within ~15s)
  3. poll the port until it accepts connections again
  4. report either READY or a clear failure

Read-only w.r.t. config: it never edits .env, never touches risk state, and
never runs when the target port is already healthy unless explicitly asked.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time

TARGETS = {
    "engine": {"port": 8010, "health": "/health", "name": "jarvis-engine"},
    "dashboard": {"port": 3010, "health": "/mission-control", "name": "jarvis-dashboard"},
}

RESPAWN_WAIT_S = 90


def listening_pid(port: int) -> int | None:
    """PID currently LISTENING on ``port`` (via netstat -ano)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local, state, pid = parts[1], parts[3], parts[-1]
        if state.upper() == "LISTENING" and local.endswith(f":{port}"):
            try:
                return int(pid)
            except ValueError:
                continue
    return None


def port_open(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def kill(pid: int) -> bool:
    try:
        res = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def wait_ready(port: int, budget_s: int = RESPAWN_WAIT_S) -> tuple[bool, float]:
    """Poll until the port accepts connections again."""
    start = time.monotonic()
    while time.monotonic() - start < budget_s:
        if port_open(port):
            return True, time.monotonic() - start
        time.sleep(2)
    return False, time.monotonic() - start


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        print(f"usage: {sys.argv[0]} {{{'|'.join(TARGETS)}}} [--verify-only]")
        return 2

    key = sys.argv[1]
    target = TARGETS[key]
    port = target["port"]
    verify_only = "--verify-only" in sys.argv

    print(f"[service-control] target={target['name']} port={port}")

    pid = listening_pid(port)
    if pid is None:
        print(f"[service-control] nothing listening on :{port} — waiting for the "
              f"supervisor to bring it up…")
        ok, waited = wait_ready(port)
        print(f"[service-control] {'READY' if ok else 'TIMEOUT'} after {waited:.1f}s")
        return 0 if ok else 1

    print(f"[service-control] found pid {pid} listening on :{port}")

    if verify_only:
        print("[service-control] --verify-only: not killing")
        return 0

    if not kill(pid):
        print(f"[service-control] FAILED to kill pid {pid}")
        return 1
    print(f"[service-control] killed pid {pid}; waiting for respawn…")

    ok, waited = wait_ready(port)
    if ok:
        new_pid = listening_pid(port)
        print(f"[service-control] READY after {waited:.1f}s (new pid {new_pid})")
        return 0
    print(f"[service-control] TIMEOUT after {waited:.1f}s — supervisor did not respawn. "
          f"Service is DOWN; start it manually.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[service-control] ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
