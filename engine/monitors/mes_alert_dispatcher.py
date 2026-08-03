"""
mes_alert_dispatcher.py

Routes MES monitor alerts to available sinks:
- dashboard API write path
- optional future discord/toast extensions

This does not execute trades.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MesAlertDispatcher:
    def __init__(self, output_dir: Path = Path("docs/morning_briefs")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def dispatch(self, alert: Dict[str, Any]) -> List[str]:
        delivered: List[str] = []
        self._write_dashboard_json(alert)
        delivered.append("dashboard")
        logger.info("Dispatched MES alert: %s", alert.get("reason"))
        return delivered

    def _write_dashboard_json(self, alert: Dict[str, Any]) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": alert.get("symbol", "MES"),
            "direction": alert.get("direction"),
            "confidence": alert.get("confidence"),
            "price": alert.get("price"),
            "reason": alert.get("reason"),
            "regime": alert.get("regime"),
        }
        path = self.output_dir / f"mes_alert_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
