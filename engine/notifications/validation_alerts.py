"""
Validation Gate Alert System — monitors 30-day paper validation gates
and fires alerts when gates flip between PASS and FAIL.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class _GateDef(TypedDict):
    target: float
    direction: str
    label: str


VALIDATION_GATES: dict[str, _GateDef] = {
    "profit_factor": {"target": 2.0, "direction": "gte", "label": "Profit Factor"},
    "sharpe_ratio": {"target": 1.5, "direction": "gte", "label": "Sharpe Ratio"},
    "win_rate": {"target": 55.0, "direction": "gte", "label": "Win Rate %"},
    "trade_count": {"target": 60, "direction": "gte", "label": "Trade Count"},
    "max_drawdown": {"target": 15.0, "direction": "lte", "label": "Max Drawdown %"},
    "trading_days": {"target": 30, "direction": "gte", "label": "Trading Days"},
}


@dataclass
class GateAlert:
    """Single gate alert event."""

    gate_name: str
    old_status: str
    new_status: str
    current_value: float
    target_value: float
    timestamp: str


class ValidationAlertManager:
    """
    Monitors validation gates and alerts on PASS/FAIL transitions.
    Persists alert history to JSON file.
    """

    def __init__(self, alert_file: str = "data/validation_alerts.json"):
        self._alert_file = Path(alert_file)
        self._alert_file.parent.mkdir(parents=True, exist_ok=True)
        self._gate_status: dict[str, str] = {}
        self._alert_history: list[dict] = []
        self._load_history()

    def evaluate_gates(self, metrics: dict) -> list[GateAlert]:
        """
        Evaluate all gates against current metrics.
        Returns list of alerts for any status changes.
        """
        alerts: list[GateAlert] = []

        # Map metric keys to gate definitions
        metric_mapping = {
            "profit_factor": "profit_factor",
            "sharpe_ratio": "sharpe_ratio",
            "win_rate_pct": "win_rate",
            "total_trades": "trade_count",
            "max_drawdown_pct": "max_drawdown",
            "days_active": "trading_days",
        }

        for metric_key, gate_name in metric_mapping.items():
            if metric_key not in metrics:
                continue

            value = float(metrics[metric_key])
            new_status = self._check_gate(gate_name, value)
            old_status = self._gate_status.get(gate_name, "UNKNOWN")

            # Status changed: create alert
            if old_status != "UNKNOWN" and old_status != new_status:
                alert = GateAlert(
                    gate_name=gate_name,
                    old_status=old_status,
                    new_status=new_status,
                    current_value=value,
                    target_value=VALIDATION_GATES[gate_name]["target"],
                    timestamp=datetime.utcnow().isoformat(),
                )
                alerts.append(alert)
                self._record_alert(alert)
                logger.info(f"Gate alert: {gate_name} {old_status} -> {new_status}")

            # Update current status
            self._gate_status[gate_name] = new_status

        return alerts

    def get_current_gate_status(self) -> dict:
        """Get current PASS/FAIL status of all gates."""
        return self._gate_status.copy()

    def get_alert_history(self) -> list[dict]:
        """Get alert history."""
        return self._alert_history.copy()

    def _check_gate(self, gate_name: str, value: float) -> str:
        """Evaluate a single gate against its threshold."""
        if gate_name not in VALIDATION_GATES:
            return "UNKNOWN"

        gate = VALIDATION_GATES[gate_name]
        target = gate["target"]
        direction = gate["direction"]

        if direction == "gte":
            return "PASS" if value >= target else "FAIL"
        elif direction == "lte":
            return "PASS" if value <= target else "FAIL"
        else:
            return "UNKNOWN"

    def _record_alert(self, alert: GateAlert) -> None:
        """Record alert to history and persist."""
        alert_dict = asdict(alert)
        self._alert_history.append(alert_dict)
        self._save_history()

        # Attempt to send notification (graceful fallback if not configured)
        self._send_notification(alert)

    def _send_notification(self, alert: GateAlert) -> None:
        """
        Fire a Discord alert for the gate transition.
        Uses asyncio.get_event_loop().create_task() for fire-and-forget from sync context.
        Graceful when event loop is not running (e.g. during tests or CLI use).
        """
        import asyncio

        try:
            from notifications import discord_notifier as _discord

            message = (
                f"VALIDATION ALERT: {alert.gate_name}\n"
                f"Status: {alert.old_status} → {alert.new_status}\n"
                f"Value: {alert.current_value:.2f} (target: {alert.target_value:.2f})"
            )

            async def _fire() -> None:
                await _discord.discord_validation_alert(
                    gate_name=alert.gate_name,
                    old_status=alert.old_status,
                    new_status=alert.new_status,
                    current_value=alert.current_value,
                    target_value=alert.target_value,
                )

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_fire())
            else:
                logger.info(f"Validation alert (no event loop): {message}")
        except Exception as e:
            logger.debug(f"Validation alert notification skipped: {e}")

    def _save_history(self) -> None:
        """Persist alert history to JSON file."""
        try:
            data = {"alerts": self._alert_history}
            self._alert_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save alert history: {e}")

    def _load_history(self) -> None:
        """Load alert history from JSON file."""
        if not self._alert_file.exists():
            return

        try:
            data = json.loads(self._alert_file.read_text())
            self._alert_history = data.get("alerts", [])
        except Exception as e:
            logger.warning(f"Failed to load alert history: {e}")
