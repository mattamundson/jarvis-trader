"""
Shared dependency stubs for auto-generated routers.

These routers (strategy_lab, notifications, alerts) are scaffolding
that will be fully implemented when their respective features ship.
This module satisfies their `from .deps import *` without errors.
"""
from typing import Any, Optional
from pydantic import BaseModel
from fastapi import BackgroundTasks  # noqa: F401 — used by strategy_lab_router
