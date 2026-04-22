"""Experiment log for n-autoresearch MES parameter search."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

EXPERIMENT_LOG_PATH = os.path.join(os.path.dirname(__file__), "experiment_log.json")


class ExperimentLog:
    def __init__(self, path: str = EXPERIMENT_LOG_PATH) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []
        if os.path.exists(path):
            with open(path) as f:
                self._records = json.load(f)

    def log(self, record: dict[str, Any]) -> None:
        record["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._records.append(record)
        with open(self.path, "w") as f:
            json.dump(self._records, f, indent=2)

    def all(self) -> list[dict[str, Any]]:
        return list(self._records)

    def best_by_wfe(self) -> dict[str, Any] | None:
        if not self._records:
            return None
        return max(self._records, key=lambda r: r.get("wfe", -1.0))

    def top_n(self, n: int = 3) -> list[dict[str, Any]]:
        return sorted(self._records, key=lambda r: r.get("wfe", -1.0), reverse=True)[:n]
