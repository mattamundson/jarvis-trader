#!/usr/bin/env python
"""Overnight MES full-grid sweep — the t_41ec4b7a infrastructure decision's cron target.

Runs the FULL default MES grid (54 combos: fast 6 x slow 3 x atr 3) x MC 10,000 on the
deep 1h cache, writes a dated results JSON, and appends a standard-template entry to
docs/BACKTEST_JOURNAL.md. Screening only — survivors still need WFO certification.

Guards (skip silently, exit 0 — the machine is not idle, per the infra decision):
  1. engine /health on 127.0.0.1:8010 must return {"status": "ok"}
  2. free physical memory >= 8 GB (the overnight-idle precondition; 0.4 GB free during
     the day OOM'd the 54-combo grid once already)
  3. lockfile engine/logs/sweep.lock — if a sweep is already running, exit 0

Env knobs (all optional):
  SWEEP_MC_RESAMPLES   default 10000
  SWEEP_SYMBOL         default MES
  SWEEP_VARIANT        default "full" (plain 54-combo grid); "vix" adds the designed
                       VIX regime block (Crisis,HighVol) as a second pass over the grid.

Exit codes: 0 = done or intentionally skipped; 2 = fatal (health down, engine crash).
Failure to launch / engine crash appends an error entry to the journal and exits 2 so
the cron runner can alert.

Path notes: launched detached by the cron launcher with the ENGINE venv python and a
stripped PYTHONPATH (Hermes harness injects its own venv, which breaks numpy/pandas).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).parent.parent.resolve()
JOURNAL = ENGINE_ROOT.parent / "docs" / "BACKTEST_JOURNAL.md"
RESULTS_DIR = ENGINE_ROOT / "backtest" / "results"
LOGS_DIR = ENGINE_ROOT / "logs"
LOCK = LOGS_DIR / "sweep.lock"
HEALTH_URL = "http://127.0.0.1:8010/health"
MIN_FREE_GB = 8.0
DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_mem_gb() -> float:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / (1024 ** 3)


def engine_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("status") == "ok")
    except Exception:
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def journal_append(text: str) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write("\n" + text.strip() + "\n")


def top_rows(doc: dict, n: int = 5) -> list[dict]:
    rows = [r for r in doc.get("rows", []) if r.get("total_trades", 0) >= 10]
    rows.sort(key=lambda r: r.get("mc_p_positive_edge") or 0, reverse=True)
    return rows[:n]


def run() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Lock: one sweep at a time.
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            if pid_alive(pid):
                print(f"SKIP: sweep already running (pid {pid})")
                return 0
        except Exception:
            pass
        LOCK.unlink(missing_ok=True)
    LOCK.write_text(str(os.getpid()))

    try:
        # Guard 1: engine health.
        if not engine_healthy():
            print("SKIP: engine /health not ok — not idle/healthy; skipping tonight")
            return 0
        # Guard 2: memory headroom.
        free = free_mem_gb()
        if free < MIN_FREE_GB:
            print(f"SKIP: free memory {free:.1f} GB < {MIN_FREE_GB} GB — machine not idle; skipping")
            return 0

        symbol = os.environ.get("SWEEP_SYMBOL", "MES")
        mc = int(os.environ.get("SWEEP_MC_RESAMPLES", "10000"))
        variant = os.environ.get("SWEEP_VARIANT", "full")

        out_path = RESULTS_DIR / f"iterate_{symbol.lower()}_full_{DATE}.json"
        cmd = [
            str(ENGINE_ROOT / ".venv" / "Scripts" / "python.exe"),
            str(ENGINE_ROOT / "backtest" / "iterate.py"),
            "--symbol", symbol,
            "--mc-resamples", str(mc),
            "--out", str(out_path),
        ]
        if variant == "vix":
            cmd += ["--vix-csv", str(ENGINE_ROOT / "backtest" / "cache" / "VIX_1990-01-02_2026-08-17_1d.csv"),
                    "--vix-regimes", "Crisis,HighVol"]

        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["OPENBLAS_NUM_THREADS"] = "2"
        env["PYTHONUNBUFFERED"] = "1"

        print(f"RUN: {cmd}  (free mem {free:.1f} GB)")
        res = subprocess.run(cmd, cwd=str(ENGINE_ROOT), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if res.returncode != 0:
            tail = res.stdout[-1500:]
            journal_append(
                f"### {DATE} — Overnight sweep FAILED (cron)\n"
                f"- **Command:** `{' '.join(cmd)}`\n"
                f"- **Exit code:** {res.returncode}\n"
                f"- **Output tail:**\n```\n{tail}\n```"
            )
            print(f"FAIL: iterate.py exited {res.returncode}; journal error entry appended")
            return 2

        doc = json.loads(out_path.read_text(encoding="utf-8"))
        best = top_rows(doc)
        rows_md = "\n".join(
            f"  {r['fast']}/{r['slow']}/{r['atr_trail_mult']} | {r['total_trades']} | "
            f"{r['profit_factor']:.4f} | {r['sharpe_ratio']:.4f} | "
            f"{r['mc_p_positive_edge']:.3f} | {r['max_drawdown_pct']*100:.2f}%"
            for r in best
        )
        journal_append(
            f"### {DATE} — Overnight {symbol} full-grid sweep (cron, t_41ec4b7a)\n"
            f"- **Harness:** `backtest/iterate.py` via `backtest/run_overnight_sweep.py`\n"
            f"- **Data:** `{doc.get('cache')}` — {doc.get('n_bars')} bars ({doc.get('span_years')}y)\n"
            f"- **Grid:** full default {symbol} grid ({doc.get('n_rows')} rows incl. VIX passes) x MC {mc}, seed 42\n"
            f"- **Weights:** risk_per_trade=0.01, capital $50k, commission 0.62, slippage 2 ticks\n"
            f"- **Results (top {len(best)} by mc_p_positive_edge, trades>=10):**\n"
            f"  combo | trades | PF | Sharpe | p_edge | DD%\n"
            f"  --- | ---: | ---: | ---: | ---: | ---:\n{rows_md}\n"
            f"- **Verdict file(s) written:** `{out_path.relative_to(ENGINE_ROOT.parent)}`\n"
            f"- **Notes:** screening only — NOT a gate verdict; survivors need WFO certification."
        )
        print(f"DONE: {doc.get('n_rows')} rows -> {out_path}; journal appended")
        return 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run())
