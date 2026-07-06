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
    1  — port held by something we won't kill: an unidentified process, or WSL2's
         wslrelay mirroring an in-WSL 0.0.0.0 bind onto the Windows loopback (refuse)
    2  — kill attempted but port still bound after grace period
    3  — port held by a HEALTHY uvicorn we can't kill (likely elevated). Exits
         non-zero so PM2 marks the start as failed (correct: we did NOT start
         a managed engine), but sleeps before exiting so PM2's restart_delay +
         min_uptime back off the restart loop instead of hammering taskkill.
         Human must kill the elevated PID via Task Manager (admin) and then
         `pm2 start jarvis-engine` to take over management.
    4  — wrong Python (Store Python instead of the project venv); exits before
         touching the port to avoid double-binding.
    5  — readiness gate fired: uvicorn was launched but never served /health within
         READINESS_DEADLINE seconds (hung/failed startup). Forced exit via the
         watchdog thread so PM2 restarts the engine instead of leaving a dead
         in-process server reported as "online". Reason logged to RESTART_LOG.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PORT = 8010
GRACE_SECONDS = 3
HEALTHY_ORPHAN_BACKOFF = 30  # seconds to sleep before exiting when orphan is healthy
                              # but unkillable — gives PM2's restart_delay+min_uptime
                              # space to mark the slot as unstable instead of looping
PORT_FREE_WAIT = 12.0         # seconds to poll after a kill before declaring failure
# Readiness gate (P0.1): the guardian launches uvicorn IN-PROCESS and blocks, so PM2
# only ever sees the guardian PID. If uvicorn never binds / never serves /health, PM2
# still reports "online" while nothing answers. A background watchdog polls /health up
# to READINESS_DEADLINE (covers the ~229s steady-state startup with margin) and forces a
# non-zero exit if the server never comes up — so PM2 actually restarts a dead engine.
READINESS_DEADLINE = 360      # seconds to wait for /health to serve before declaring the start dead
READINESS_POLL = 5            # seconds between readiness probes
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = ENGINE_DIR.parent
RESTART_LOG = ENGINE_DIR / "logs" / "port_guardian_restarts.jsonl"  # structured restart-reason trail


def _record_restart_event(reason: str, details: dict, log_path: Path) -> None:
    """Append a structured restart-reason record (JSONL) so a restart's cause is
    no longer invisible. Never raises — logging must not break the guardian."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "pid": os.getpid(),
        "details": details,
    }
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _readiness_watchdog(
    deadline_s: float,
    poll_interval_s: float,
    is_ready_fn,
    *,
    now_fn=time.monotonic,
    sleep_fn=time.sleep,
) -> bool:
    """Poll ``is_ready_fn`` until it returns True (→ True) or ``deadline_s`` elapses
    (→ False). Clock/sleep are injectable so the loop is deterministically testable."""
    start = now_fn()
    while (now_fn() - start) < deadline_s:
        if is_ready_fn():
            return True
        sleep_fn(poll_interval_s)
    return False


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


def _is_wsl_relay(name: str | None) -> bool:
    """True if the port holder is WSL2's localhost-forwarding relay (wslrelay.exe).

    When a process INSIDE WSL binds ``0.0.0.0:PORT``, WSL2 mirrors it onto the Windows
    loopback via ``wslrelay``. From Windows the port then looks held by ``wslrelay``,
    which is NOT ours to kill -- killing it would tear down ALL WSL port forwarding.
    Detecting it lets the guardian emit an actionable diagnosis instead of the generic
    "not a python/uvicorn process" line, which flapped 81k+ times with no usable cause
    on 2026-07-04 (a stray ``python3 -m http.server 8010`` in WSL squatted the port)."""
    return bool(name) and name.lower() in {"wslrelay", "wslrelay.exe"}


def _verify_free(port: int, retries: int = 5, delay: float = 0.5) -> bool:
    """Probe the port; return True if nothing answers."""
    for _ in range(retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            try:
                s.connect(("127.0.0.1", port))
                time.sleep(delay)
                continue
            except (ConnectionRefusedError, socket.timeout):
                return True
    return False


def _wait_port_free(port: int, timeout: float = PORT_FREE_WAIT) -> bool:
    """Poll until port is free or timeout expires. Returns True if free."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _verify_free(port, retries=1, delay=0.0):
            return True
        time.sleep(0.5)
    return False


def _kill_pid(pid: int) -> bool:
    """Kill a process: taskkill first, PowerShell Stop-Process as fallback.

    taskkill can fail with exit code 1 for same-elevation processes in some
    Windows states (e.g. process in DPC/APC wait). Stop-Process is more
    reliable in that case. Returns True if either method succeeded.
    """
    # Primary: taskkill /F
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=True, timeout=10, capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # Fallback: PowerShell Stop-Process -Force
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {pid} -Force -ErrorAction Stop"],
            check=True, timeout=10, capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _is_healthy(port: int) -> bool:
    """True if /health returns HTTP 200 quickly."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionResetError):
        return False


def _check_venv_python() -> None:
    """Exit immediately if running under Store Python instead of the project venv.

    The PM2 venv python sometimes spawns a Store Python child that also tries to
    bind port 8010. This guard breaks that cycle by making any non-venv invocation
    exit before touching the port.
    """
    import sys
    exe = sys.executable.lower()
    venv_marker = ".venv"
    store_marker = "windowsapps"
    if store_marker in exe or venv_marker not in exe:
        print(
            f"[port_guardian] WRONG PYTHON: {sys.executable!r} is not the project venv. "
            "Exiting to prevent double-binding port 8010.",
            flush=True,
        )
        sys.exit(4)


def _start_readiness_watchdog() -> None:
    """Spawn a daemon thread that confirms uvicorn actually serves /health within
    READINESS_DEADLINE. If it never does, record the reason and force a non-zero exit
    so PM2 restarts the engine instead of leaving a dead server reported as 'online'."""

    def _watch() -> None:
        ready = _readiness_watchdog(
            READINESS_DEADLINE, READINESS_POLL, lambda: _is_healthy(PORT)
        )
        if ready:
            print("[port_guardian] readiness confirmed — /health is serving", flush=True)
            return
        _record_restart_event(
            "health-timeout",
            {"port": PORT, "deadline_s": READINESS_DEADLINE},
            RESTART_LOG,
        )
        print(
            f"[port_guardian] uvicorn did not serve /health within {READINESS_DEADLINE}s "
            "— forcing exit so PM2 restarts the engine",
            flush=True,
        )
        os._exit(5)

    threading.Thread(target=_watch, name="readiness-watchdog", daemon=True).start()


def main() -> int:
    _check_venv_python()
    print(f"[port_guardian] checking port {PORT}...", flush=True)
    holders = _port_holders(PORT)

    if not holders:
        print(f"[port_guardian] port {PORT} is free", flush=True)
    else:
        for pid in holders:
            name = _process_name(pid) or "unknown"
            print(f"[port_guardian] port {PORT} held by PID {pid} ({name})", flush=True)
            if not _looks_like_orphan_uvicorn(pid):
                if _is_wsl_relay(name):
                    print(
                        f"[port_guardian] port {PORT} is held by wslrelay (PID {pid}): a "
                        f"process INSIDE WSL is bound to 0.0.0.0:{PORT} and WSL2 "
                        f"localhost-forwarding is mirroring it onto Windows "
                        f"127.0.0.1:{PORT}. Killing wslrelay would break ALL WSL port "
                        f"forwarding, so REFUSING. Fix in WSL: run "
                        f"`wsl ss -ltnp | grep :{PORT}` then kill the offending PID inside WSL.",
                        flush=True,
                    )
                    _record_restart_event(
                        "wsl-port-squat",
                        {"pid": pid, "name": name, "port": PORT},
                        RESTART_LOG,
                    )
                    return 1
                print(
                    f"[port_guardian] PID {pid} is not a python/uvicorn process — "
                    "REFUSING to kill. Resolve manually.",
                    flush=True,
                )
                return 1
            print(f"[port_guardian] killing orphan PID {pid}", flush=True)
            killed = _kill_pid(pid)
            if killed:
                _record_restart_event(
                    "orphan-kill", {"pid": pid, "name": name, "port": PORT}, RESTART_LOG
                )
            if not killed:
                # Both taskkill and Stop-Process failed — process is likely elevated.
                if _is_healthy(PORT):
                    print(
                        f"[port_guardian] CANNOT kill PID {pid} (likely elevated). "
                        f"Engine on port {PORT} IS healthy — exiting non-zero after "
                        f"{HEALTHY_ORPHAN_BACKOFF}s backoff. "
                        f"ACTION REQUIRED: kill PID {pid} via Task Manager (admin) "
                        f"then `pm2 start jarvis-engine`.",
                        flush=True,
                    )
                    time.sleep(HEALTHY_ORPHAN_BACKOFF)
                    return 3
                print(
                    f"[port_guardian] CANNOT kill PID {pid} (both taskkill and "
                    "Stop-Process failed, not elevated-healthy). Aborting.",
                    flush=True,
                )
                return 2

        # Poll until the OS releases the bind (up to PORT_FREE_WAIT seconds)
        if not _wait_port_free(PORT):
            print(
                f"[port_guardian] port {PORT} still bound {PORT_FREE_WAIT}s after kill — "
                "aborting",
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
    for path in (str(PROJECT_ROOT), str(ENGINE_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import uvicorn  # noqa: PLC0415 — deferred import so the cleanup phase above stays cheap

    # Readiness gate: watch from a side thread that uvicorn actually serves /health.
    # If startup hangs / never binds, this forces a non-zero exit so PM2 truly restarts
    # the engine instead of reporting a dead in-process server as "online".
    _start_readiness_watchdog()

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


