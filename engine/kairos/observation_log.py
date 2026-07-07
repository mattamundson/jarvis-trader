"""
KAIROS — Observation Log
=========================
Append-only JSONL observation log. One file per day in data/kairos/.
Thread-safe for single-process asyncio usage.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .watchers import Observation

logger = logging.getLogger(__name__)


class ObservationLog:
    """
    Append-only JSONL observation log.
    One file per calendar day: data/kairos/YYYY-MM-DD.jsonl
    """

    def __init__(self, base_dir: str = "data/kairos") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_file(self, d: Optional[date] = None) -> Path:
        d = d or date.today()
        return self.base_dir / f"{d.isoformat()}.jsonl"

    # ── Write ──────────────────────────────────────────────────────────────

    def append(self, obs: Observation) -> None:
        """Append a single observation to today's JSONL log file."""
        line = json.dumps(
            {
                "timestamp": obs.timestamp,
                "watcher": obs.watcher,
                "severity": obs.severity.value,
                "message": obs.message,
                "data": obs.data,
                "notify": obs.notify,
                "symbol": obs.symbol,
            },
            ensure_ascii=False,
        )
        try:
            with open(self._get_file(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            logger.error(f"ObservationLog.append failed: {exc}")

    # ── Read ───────────────────────────────────────────────────────────────

    def read_today(self) -> list[dict]:
        """Return all observations logged today."""
        return self.read_date(date.today().isoformat())

    def read_date(self, date_str: str) -> list[dict]:
        """Return all observations for a given ISO date string."""
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            logger.warning(f"ObservationLog.read_date: invalid date '{date_str}'")
            return []

        path = self._get_file(d)
        if not path.exists():
            return []

        results: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        f"ObservationLog: skipping malformed JSON on line {line_no} "
                        f"of {path.name}: {exc}"
                    )
        return results

    def get_recent(self, minutes: int = 60) -> list[dict]:
        """Return observations from the last N minutes (today's log only)."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        all_obs = self.read_today()
        result: list[dict] = []
        for o in all_obs:
            try:
                ts = datetime.fromisoformat(o["timestamp"])
                if ts > cutoff:
                    result.append(o)
            except (KeyError, ValueError):
                continue
        return result

    def count_by_severity(self, date_str: str = None) -> dict:
        """Return observation counts grouped by severity for a given date (default today)."""
        obs = self.read_date(date_str) if date_str else self.read_today()
        counts: dict[str, int] = {"info": 0, "warning": 0, "critical": 0}
        for o in obs:
            sev = o.get("severity", "info")
            counts[sev] = counts.get(sev, 0) + 1
        return counts
