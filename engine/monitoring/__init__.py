"""Monitoring and observability for JARVIS TRADER."""

from . import predictive_maintenance  # noqa: F401 — ensure submodule importable
from .metrics import (
    record_llm_call,
    record_llm_cost,
    record_order,
    record_pipeline_duration,
    record_pipeline_run,
    record_safety_event,
    set_consecutive_losses,
    set_daily_pnl,
    set_equity,
    set_kill_switch,
)

__all__ = [
    "record_pipeline_run",
    "record_pipeline_duration",
    "record_llm_call",
    "record_llm_cost",
    "record_order",
    "set_daily_pnl",
    "set_equity",
    "set_kill_switch",
    "record_safety_event",
    "set_consecutive_losses",
]
