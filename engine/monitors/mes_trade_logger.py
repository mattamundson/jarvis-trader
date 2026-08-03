"""
mes_trade_logger.py

Logs monitor suggestions and outcomes for later review.
No execution side effects.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorSuggestion:
    timestamp: str
    symbol: str
    direction: str
    confidence: float
    price: float
    reason: str
    regime_reason: str
    risk_scale: float


class MesTradeLogger:
    def __init__(self, csv_path: Path = Path("data/mes_monitor_suggestions.csv")) -> None:
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(MonitorSuggestion.__annotations__.keys()))
                writer.writeheader()

    def log(self, suggestion: MonitorSuggestion) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(MonitorSuggestion.__annotations__.keys()))
            writer.writerow(asdict(suggestion))
        logger.info("Logged MES suggestion: %s @ %s", suggestion.direction, suggestion.price)
