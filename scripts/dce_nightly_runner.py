#!/usr/bin/env python3
"""Run DiscordChatExporter safely without placing tokens in argv."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "engine"
EXPORTS = Path.home() / "discord-export"
TOKEN_FILE = Path(os.environ.get("DCE_TOKEN_FILE") or EXPORTS / ".token")
LOG_DIR = ENGINE / "logs"
LOG_FILE = LOG_DIR / "dce_nightly.log"
STREAK_FILE = LOG_DIR / "dce_failure_streak.txt"
RUNBOOK = REPO / "docs" / "runbooks" / "verify-dce-ibg-activation.md"
DCE = Path(os.environ.get("DCE_CLI_PATH") or r"C:\Users\mattm\tools\DiscordChatExporter.Cli\DiscordChatExporter.Cli.exe")
PYTHON = ENGINE / ".venv" / "Scripts" / "python.exe"
CHANNELS = [
    ("market-updates", "806343100435660801"),
    ("general", "741484321142997086"),
]


def log(level: str, msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} [{level}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_env_value(name: str) -> str | None:
    env_path = ENGINE / ".env"
    if not env_path.exists():
        return None
    pat = re.compile(rf"^{re.escape(name)}=(.*)$")
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pat.match(raw.strip())
        if not m:
            continue
        value = re.sub(r"\s+#.*$", "", m.group(1).strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        return value.strip()
    return None


def get_token() -> str | None:
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        if token:
            return token
    return read_env_value("DISCORD_TOKEN")


def get_streak() -> int:
    try:
        return int(STREAK_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def set_streak(n: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STREAK_FILE.write_text(str(n), encoding="utf-8")


def main() -> int:
    log("INFO", "=== dce-nightly start ===")
    if not DCE.exists():
        log("ERROR", f"DCE not found at {DCE} — set DCE_CLI_PATH or install DiscordChatExporter.CLI")
        return 2
    EXPORTS.mkdir(parents=True, exist_ok=True)
    token = get_token()
    if not token:
        log("ERROR", f"Discord token missing: neither {TOKEN_FILE} nor engine/.env DISCORD_TOKEN is populated")
        return 3

    env = os.environ.copy()
    env["DISCORD_TOKEN"] = token
    after = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    failed: list[str] = []

    for name, channel_id in CHANNELS:
        log("INFO", f"Exporting {name} ({channel_id}) after {after}")
        cmd = [str(DCE), "export", "-c", channel_id, "-o", str(EXPORTS), "-f", "Json", "--after", after, "--respect-rate-limits"]
        proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        output = (proc.stdout or b"").decode("utf-8", errors="replace")
        for line in output.splitlines():
            # DCE does not echo DISCORD_TOKEN in this mode; keep logs concise anyway.
            if "Authentication token is invalid" in line:
                log("DCE", "Authentication token is invalid")
            elif line.strip():
                log("DCE", line[:500])
        if proc.returncode != 0:
            if "Authentication token is invalid" in output:
                log(
                    "ERROR",
                    "blocker=invalid_discord_token "
                    f"channel={name} runbook={RUNBOOK} "
                    "fix=write_fresh_discord_user_token_to_C:/Users/mattm/discord-export/.token "
                    "then_rerun=scripts/dce-nightly.ps1",
                )
            else:
                log("ERROR", f"Export failed for {name}: DCE exited {proc.returncode}")
            failed.append(name)
        else:
            log("INFO", f"Export OK: {name}")

    if failed:
        log("ERROR", "Channel exports failed: " + ", ".join(failed))
        streak = get_streak() + 1
        set_streak(streak)
        log("WARN", f"Failure streak now {streak} day(s)")
        if streak >= 2:
            log(
                "WARN",
                "blocker=invalid_discord_token stale_sentiment_alert=active "
                f"runbook={RUNBOOK} log={LOG_FILE}",
            )
        return 10

    set_streak(0)
    if not PYTHON.exists():
        log("ERROR", f"Python venv not found at {PYTHON} — skipping ingest")
        return 20
    log("INFO", "Chaining scripts.nightly_discord for ingest + sentiment ETL")
    proc = subprocess.run([str(PYTHON), "-m", "scripts.nightly_discord"], cwd=str(ENGINE), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            log("ETL", line[:500])
    if proc.returncode != 0:
        log("ERROR", f"Ingest/ETL failed: nightly_discord exited {proc.returncode}")
        return 20
    log("INFO", "Ingest + ETL complete")
    log("INFO", "=== dce-nightly complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
