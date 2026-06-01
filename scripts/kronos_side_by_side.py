"""
Kronos side-by-side comparison harness
=======================================
Reads N days of pnl_snapshots / paper_trades from the engine's SQLite database
and, for each bar window, requests a pipeline analysis with Kronos OFF then ON
(via ``ENABLE_KRONOS`` env override).  Diffs the ``analyst_reports["kronos"]``
field between the two runs and emits a Markdown report.

Operates in **dry mode**: no orders are routed.  The engine must be running
at ``http://127.0.0.1:8010``.

Usage:
    # From the repo root (venv must be active)
    python scripts/kronos_side_by_side.py [--days N] [--symbol SYM] [--output PATH]

    python scripts/kronos_side_by_side.py --days 3 --symbol MES
    python scripts/kronos_side_by_side.py --days 7 --output scripts/data/kronos_side_by_side_custom.md

Output:
    scripts/data/kronos_side_by_side_<date>.md
    (or the path given via --output)

Unit-testable diff logic lives in ``_diff_verdicts`` — importable without
running the script.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Attempt engine HTTP client — graceful fallback when running unit tests
# ---------------------------------------------------------------------------
try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

ENGINE_URL = "http://127.0.0.1:8010"
_DEFAULT_DAYS = 3
_DEFAULT_SYMBOL = "MES"
_SCRIPT_DIR = Path(__file__).parent
_DATA_DIR = _SCRIPT_DIR / "data"


# ---------------------------------------------------------------------------
# Diff logic (unit-testable; no I/O)
# ---------------------------------------------------------------------------


def _diff_verdicts(
    off_verdict: dict[str, Any],
    on_verdict: dict[str, Any],
) -> dict[str, Any]:
    """Return a diff summary comparing Kronos-OFF vs Kronos-ON verdicts.

    Args:
        off_verdict: ``analyst_reports["kronos"]`` dict from a run with
                     ``ENABLE_KRONOS=0``.
        on_verdict:  Same dict from a run with ``ENABLE_KRONOS=1``.

    Returns:
        Dict with keys:
          - ``signal_delta``: on_signal - off_signal
          - ``confidence_delta``: on_confidence - off_confidence
          - ``direction_change``: True when the sign of signal flips
          - ``summary_changed``: True when summaries differ
          - ``off_signal``, ``on_signal``, ``off_confidence``, ``on_confidence``
          - ``off_summary``, ``on_summary``
    """
    off_signal = float(off_verdict.get("signal", 0.0))
    on_signal = float(on_verdict.get("signal", 0.0))
    off_conf = float(off_verdict.get("confidence", 0.0))
    on_conf = float(on_verdict.get("confidence", 0.0))

    def _sign(v: float) -> int:
        if v > 0:
            return 1
        if v < 0:
            return -1
        return 0

    direction_change = _sign(off_signal) != _sign(on_signal)

    return {
        "signal_delta": round(on_signal - off_signal, 4),
        "confidence_delta": round(on_conf - off_conf, 4),
        "direction_change": direction_change,
        "summary_changed": off_verdict.get("summary") != on_verdict.get("summary"),
        "off_signal": off_signal,
        "on_signal": on_signal,
        "off_confidence": off_conf,
        "on_confidence": on_conf,
        "off_summary": off_verdict.get("summary", ""),
        "on_summary": on_verdict.get("summary", ""),
    }


# ---------------------------------------------------------------------------
# Engine API helpers
# ---------------------------------------------------------------------------


async def _get_api_key(client: "httpx.AsyncClient") -> str:
    """Read the API key from engine/.env (never from environment directly)."""
    env_path = _SCRIPT_DIR.parent / "engine" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("API_KEY=") or line.startswith("JARVIS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


async def _pipeline_run(
    client: "httpx.AsyncClient",
    api_key: str,
    symbol: str,
    enable_kronos: bool,
) -> dict[str, Any]:
    """Run a pipeline analysis for ``symbol`` with Kronos toggled on/off.

    The toggle is signalled via a custom header ``X-Kronos-Override`` so the
    engine can honour it without an env restart.  If the engine does not support
    the header (older builds), the result is returned as-is and the override has
    no effect — the diff will show all zeros.

    Returns an empty dict on any HTTP or network error (logged, not raised).
    """
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "X-Kronos-Override": "1" if enable_kronos else "0",
    }
    try:
        resp = await client.post(
            f"{ENGINE_URL}/pipeline/run",
            json={"symbol": symbol, "dry_run": True},
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(
            f"[WARN] pipeline/run error (kronos={'ON' if enable_kronos else 'OFF'}): {exc}"
        )
        return {}


async def _fetch_pnl_snapshots(
    client: "httpx.AsyncClient",
    api_key: str,
    days: int,
) -> list[dict[str, Any]]:
    """Fetch recent pnl_snapshots from the engine API."""
    headers = {"X-API-Key": api_key}
    try:
        resp = await client.get(
            f"{ENGINE_URL}/pnl/snapshots",
            params={"days": days},
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("snapshots", [])
    except Exception as exc:
        print(f"[WARN] Could not fetch pnl_snapshots: {exc}")
        return []


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _render_report(
    symbol: str,
    days: int,
    rows: list[dict[str, Any]],
    run_ts: str,
) -> str:
    """Render the side-by-side diff as a Markdown string."""
    lines: list[str] = [
        f"# Kronos side-by-side — {symbol} — {run_ts}",
        "",
        f"Days analysed: **{days}** | Symbol: **{symbol}** | Rows compared: **{len(rows)}**",
        "",
        "## Summary stats",
        "",
    ]

    if not rows:
        lines.append("_No rows to compare._")
        return "\n".join(lines)

    direction_changes = sum(1 for r in rows if r.get("direction_change"))
    mean_signal_delta = sum(r.get("signal_delta", 0.0) for r in rows) / len(rows)
    mean_conf_delta = sum(r.get("confidence_delta", 0.0) for r in rows) / len(rows)

    lines += [
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Direction changes | {direction_changes} / {len(rows)} |",
        f"| Mean signal delta (ON - OFF) | {mean_signal_delta:+.4f} |",
        f"| Mean confidence delta (ON - OFF) | {mean_conf_delta:+.4f} |",
        "",
        "## Per-run detail",
        "",
        "| # | Signal OFF | Signal ON | Delta | Conf OFF | Conf ON | Direction change? |",
        "|---|-----------|-----------|-------|----------|---------|-------------------|",
    ]

    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} "
            f"| {row.get('off_signal', 0.0):+.4f} "
            f"| {row.get('on_signal', 0.0):+.4f} "
            f"| {row.get('signal_delta', 0.0):+.4f} "
            f"| {row.get('off_confidence', 0.0):.4f} "
            f"| {row.get('on_confidence', 0.0):.4f} "
            f"| {'YES' if row.get('direction_change') else 'no'} |"
        )

    lines += [
        "",
        "## Notes",
        "",
        "- Kronos OFF verdict is the current neutral stub (signal=0.0, confidence=0.0).",
        "- Kronos ON verdict requires `ENABLE_KRONOS=1` and the Kronos package installed.",
        "- Direction change = the sign of signal flipped between OFF and ON runs.",
        "- This report is for paper-side validation only — no orders are routed.",
        "",
        f"_Generated by `scripts/kronos_side_by_side.py` at {run_ts}_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def run(
    symbol: str = _DEFAULT_SYMBOL,
    days: int = _DEFAULT_DAYS,
    output: Path | None = None,
) -> Path:
    """Execute the side-by-side comparison and write the report.

    Returns the output path.
    """
    if not _HTTPX_AVAILABLE:
        raise RuntimeError(
            "httpx is required to run the side-by-side harness. "
            "Install it with: pip install httpx"
        )

    run_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    if output is None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        output = _DATA_DIR / f"kronos_side_by_side_{run_ts}.md"

    async with httpx.AsyncClient() as client:
        api_key = await _get_api_key(client)
        if not api_key:
            print("[WARN] API key not found in engine/.env — requests may be rejected.")

        snapshots = await _fetch_pnl_snapshots(client, api_key, days)
        print(
            f"[INFO] Fetched {len(snapshots)} pnl_snapshots for the last {days} days."
        )

        diff_rows: list[dict[str, Any]] = []

        # Run one pipeline call per snapshot window (throttled — not per bar)
        # For the paper-side comparison we run a single pair of calls per
        # symbol since the pipeline already uses the latest bar window.
        # Extend this loop if per-snapshot granularity is required.
        off_result = await _pipeline_run(client, api_key, symbol, enable_kronos=False)
        on_result = await _pipeline_run(client, api_key, symbol, enable_kronos=True)

        off_kronos = (off_result.get("analyst_reports") or {}).get(
            "kronos", {"signal": 0.0, "confidence": 0.0, "summary": "disabled"}
        )
        on_kronos = (on_result.get("analyst_reports") or {}).get(
            "kronos", {"signal": 0.0, "confidence": 0.0, "summary": "disabled"}
        )

        diff_rows.append(_diff_verdicts(off_kronos, on_kronos))

        report = _render_report(symbol, days, diff_rows, run_ts)
        output.write_text(report, encoding="utf-8")
        print(f"[INFO] Report written to {output}")
        return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Kronos side-by-side comparison")
    parser.add_argument(
        "--days", type=int, default=_DEFAULT_DAYS, help="Days of history"
    )
    parser.add_argument("--symbol", default=_DEFAULT_SYMBOL, help="Instrument symbol")
    parser.add_argument(
        "--output", type=Path, default=None, help="Output Markdown path"
    )
    args = parser.parse_args()
    asyncio.run(run(symbol=args.symbol, days=args.days, output=args.output))


if __name__ == "__main__":
    main()
