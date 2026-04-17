"""
Port Guardian — pre-flight check for jarvis-engine.

Ensures port 8010 is free before launching uvicorn. If an orphaned process
holds the port (typically from a prior PM2 crash or a manual `restart_engine.ps1`
launch that left a Store Python uvicorn behind), this script identifies and
kills it, then exec's uvicorn cleanly.

Background: 2026-04-14 incident — jarvis-engine crash-looped 1,248 times because
a PowerShell-launched uvicorn from earlier in the day was holding port 8010.
PM2 spawned a new engine every 30s, it failed to bind, exited, restart, repeat.
Each restart flashed a cmd window. See docs/troubleshooting.md for full forensic.

Usage (replaces direct uvicorn invocation in ecosystem.config.js):
    python scripts/port_guardian.py
        — runs the check, then exec's:
        uvicorn main:app --host 0.0.0.0 --port 8010

Exit codes:
    0  — port was free or orphan killed cleanly; uvicorn started
    1  — port held by something we can't identify (refuse to kill)
    2  — kill attempted but port still bound after grace period
    3  — port held by a HEALTHY uvicorn we can't kill (likely elevated). Exits
         non-zero so PM2 marks the start as failed (correct: we did NOT start
         a managed engine), but sleeps before exiting so PM2's restart_delay +
         min_uptime back off the restart loop instead of hammering taskkill.
         Human must kill the elevated PID via Task Manager (admin) and then
         `pm2 start jarvis-engine` to take over management.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8010
GRACE_SECONDS = 3
HEALTHY_ORPHAN_BACKOFF = 30  # seconds to sleep before exiting when orphan is healthy
                              # but unkillable — gives PM2's restart_delay+min_uptime
                              # space to mark the slot as unstable instead of looping
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPT_DIR.parent


def _port_holders(port: int) -> list[int]:
    """Return PIDs that are LISTENING on the given port (TCP)."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    pids: set[int] = set()
    needle = f":{port} "
    for line in out.splitlines():
        if needle not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def _process_name(pid: int) -> str | None:
    """Best-effort process name lookup. Returns None on failure."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty ProcessName"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _looks_like_orphan_uvicorn(pid: int) -> bool:
    """
    Conservative check: only kill processes that look like uvicorn/python.
    Refuses to kill anything else (e.g. a debugger, Excel, etc).
    """
    name = _process_name(pid)
    if not name:
        return False
    return name.lower() in {"python", "python3.12", "python3.11", "python3.10", "uvicorn"}


def _verify_free(port: int, retries: int = 5, delay: float = 0.5) -> bool:
    """Probe the port; return True if nothing answers."""
    for _ in range(retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            try:
                s.connect(("127.0.0.1", port))
                # Connected — port is in use
                time.sleep(delay)
                continue
            except (ConnectionRefusedError, socket.timeout):
                return True
    return False


def _is_healthy(port: int) -> bool:
    """True if /health returns HTTP 200 quickly."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionResetError):
        return False


def main() -> int:
    print(f"[port_guardian] checking port {PORT}...", flush=True)
    holders = _port_holders(PORT)

    if not holders:
        print(f"[port_guardian] port {PORT} is free", flush=True)
    else:
        for pid in holders:
            name = _process_name(pid) or "unknown"
            print(f"[port_guardian] port {PORT} held by PID {pid} ({name})", flush=True)
            if not _looks_like_orphan_uvicorn(pid):
                print(
                    f"[port_guardian] PID {pid} is not a python/uvicorn process — "
                    "REFUSING to kill. Resolve manually.",
                    flush=True,
                )
                return 1
            print(f"[port_guardian] killing orphan PID {pid}", flush=True)
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    check=True,
                    timeout=10,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                # Most common failure: target process is elevated and we're not.
                # Check if the orphan is at least healthy — if yes, sleep+exit
                # cleanly so PM2 doesn't crash-loop us hammering taskkill.
                if _is_healthy(PORT):
                    print(
                        f"[port_guardian] CANNOT kill PID {pid} (likely elevated). "
                        f"Engine on port {PORT} IS healthy and serving — exiting non-zero "
                        f"after {HEALTHY_ORPHAN_BACKOFF}s backoff. "
                        f"ACTION REQUIRED: kill PID {pid} via Task Manager (admin) "
                        f"then `pm2 start jarvis-engine` to bring under PM2 management.",
                        flush=True,
                    )
                    time.sleep(HEALTHY_ORPHAN_BACKOFF)
                    return 3
                print(f"[port_guardian] taskkill failed for PID {pid}: {exc}", flush=True)
                return 2

        # Wait for the OS to release the bind
        time.sleep(GRACE_SECONDS)
        if not _verify_free(PORT):
            print(
                f"[port_guardian] port {PORT} still bound after grace period — aborting",
                flush=True,
            )
            return 2
        print(f"[port_guardian] port {PORT} released", flush=True)

    # All clear — launch uvicorn IN-PROCESS so PM2 tracks a single stable PID.
    #
    # Why not os.execvp? On POSIX, execvp replaces the calling process with
    # uvicorn and the PID is preserved. On Windows, execvp spawns a NEW process
    # with a NEW PID and the guardian process exits — PM2 then sees the tracked
    # PID vanish, marks the app as crashed, and restarts the guardian. Worse,
    # the spawned uvicorn child is often orphaned and accumulates. That's the
    # class of bug behind the 2026-04-16 thirty-orphan cleanup.
    #
    # Calling ``uvicorn.run()`` keeps the guardian process alive as the uvicorn
    # server (guardian does ``import uvicorn`` then hands control over). PM2
    # sees one long-lived PID; shutdown signals propagate normally.
    print("[port_guardian] launching uvicorn in-process", flush=True)
    os.chdir(ENGINE_DIR)
    import uvicorn  # noqa: PLC0415 — deferred import so the cleanup phase above stays cheap
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
    # uvicorn.run blocks until the server is shut down; 0 is the normal exit.
    return 0


if __name__ == "__main__":
    sys.exit(main())
