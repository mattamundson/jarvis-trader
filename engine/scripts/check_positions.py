#!/usr/bin/env python3
"""Read and print JARVIS broker positions without hardcoded credentials.

Imported/sanitized from mattamundson/jarvis-positions-check during the
2026-09-12 repository-consolidation Wave 1 pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ENGINE_URL = "http://127.0.0.1:8010"
DEFAULT_ENDPOINT = "/brokers/positions"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def format_positions_response(data: dict[str, Any]) -> str:
    """Return a human-readable positions summary from engine JSON."""

    def fmt_pos(positions: list[dict[str, Any]], label: str) -> list[str]:
        if not positions:
            return []
        rows = [f"  [{label}]"]
        for position in positions:
            symbol = position.get("symbol", "?")
            side = position.get("side") or position.get("direction", "?")
            quantity = position.get("quantity") or position.get("contracts", "?")
            entry_price = _num(position.get("avg_cost") or position.get("entry_price"))
            pnl = _num(position.get("unrealized_pnl") or position.get("pnl"))
            entry_text = f"@{entry_price:.2f}" if entry_price is not None else ""
            pnl_text = f"  pnl={pnl:+.2f}" if pnl is not None else ""
            rows.append(f"    {symbol:<6} {side:<5} x{quantity}{entry_text}{pnl_text}")
        return rows

    ibkr = data.get("ibkr") if isinstance(data.get("ibkr"), dict) else {}
    schwab = data.get("schwab") if isinstance(data.get("schwab"), dict) else {}
    paper = data.get("paper") if isinstance(data.get("paper"), dict) else {}

    ibkr_positions = ibkr.get("positions") or []
    schwab_positions = schwab.get("positions") or []
    paper_positions = paper.get("positions") or []

    lines = [f"Positions (IBKR {'connected' if ibkr.get('connected') else 'DISCONNECTED'}):"]
    lines += fmt_pos(ibkr_positions, "IBKR")
    lines += fmt_pos(schwab_positions, "Schwab")
    lines += fmt_pos(paper_positions, "Paper")

    if len(ibkr_positions) + len(schwab_positions) + len(paper_positions) == 0:
        lines.append("  No open positions.")

    return "\n".join(lines)


def fetch_positions(engine_url: str, api_key: str, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch positions from the configured JARVIS engine."""
    url = engine_url.rstrip("/") + endpoint
    request = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
        return json.loads(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print JARVIS engine positions.")
    parser.add_argument("--engine-url", default=os.environ.get("JARVIS_ENGINE_URL", DEFAULT_ENGINE_URL))
    parser.add_argument("--endpoint", default=os.environ.get("JARVIS_POSITIONS_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--api-key", default=os.environ.get("JARVIS_API_KEY") or os.environ.get("API_KEY"))
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.api_key:
        print("[positions] Missing API key. Set JARVIS_API_KEY or API_KEY, or pass --api-key.", file=sys.stderr)
        return 2
    try:
        data = fetch_positions(args.engine_url, args.api_key, args.endpoint, args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"[positions] Engine returned HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - exact network exceptions vary by platform
        print(f"[positions] Engine unreachable: {exc}", file=sys.stderr)
        return 1

    print(format_positions_response(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
