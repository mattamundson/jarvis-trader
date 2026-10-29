#!/usr/bin/env python3
"""Watchdog: auto-restart pusher if crashed or stale."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / "tape" / "logs" / "watchdog.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    print(line.rstrip())
    with open(LOG_FILE, "a") as f:
        f.write(line)

def is_pusher_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        return len(result.stdout.strip().split("\n")) > 1
    except Exception as e:
        log(f"ERROR: Failed to check process: {e}")
        return False

def check_data_freshness() -> int | None:
    health_url = os.environ.get("FLOW_PUSH_URL", "").replace("/ingest", "/health")
    if not health_url.endswith("/health"):
        return None
    
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            return data.get("age_seconds", 999)
    except Exception as e:
        log(f"ERROR: Health check failed: {e}")
        return None

def start_pusher() -> bool:
    batch_file = Path.home() / "tape" / "start_flow_pusher.bat"
    if not batch_file.exists():
        log(f"ERROR: Batch file not found at {batch_file}")
        return False
    
    try:
        subprocess.Popen(
            [str(batch_file)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            shell=True
        )
        log("SUCCESS: Started pusher")
        return True
    except Exception as e:
        log(f"ERROR: Failed to start: {e}")
        return False

def main():
    log("=" * 60)
    running = is_pusher_running()
    age = check_data_freshness()
    
    if not running or (age and age > 120):
        log(f"UNHEALTHY: {'not running' if not running else f'stale ({age}s)'}")
        if start_pusher():
            time.sleep(10)
            return 0 if is_pusher_running() else 1
        return 1
    
    log("OK: Healthy")
    return 0

if __name__ == "__main__":
    sys.exit(main())
