"""
JARVIS TRADER — RL Strategy API Router (DEPRECATED)
=====================================================
DEPRECATED: This router is not currently mounted in main.py.
All RL training endpoints are served by strategies_router.py which provides
comprehensive multi-window training, deployment, and executor management.

If future single-strategy lightweight operations are needed, this router
can be revived with a narrow, specialized set of endpoints not conflicting
with strategies_router.

Marked for removal in Phase 2 (US-209 learning modules cleanup).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Module-level trainer (deprecated, not used) ───────────────────────

_trainer: Optional[object] = None


def set_data_manager(data_manager) -> None:
    """Deprecated: this router is not mounted in main.py."""
    global _trainer
    _trainer = data_manager
    logger.warning(
        "[StrategyRouter] set_data_manager called on deprecated router (not mounted in main.py)"
    )


# ── Request / Response Models (for potential future use) ──────────────────────


class TrainRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol: MES, MNQ, MCL")
    interval: str = Field("1h", description="Bar interval: 1h, 4h, 1d")
    timesteps: int = Field(
        100_000,
        ge=10_000,
        le=1_000_000,
        description="PPO training timesteps",
    )


class EvaluateRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol")
    model_path: str = Field(..., description="Path to saved model .zip (without extension)")
    interval: str = Field("1h")


# ── Deprecation Notice ────────────────────────────────────────────────────────
# All endpoints below are DISABLED and should NOT be called.
# Use /strategies/* endpoints from strategies_router instead:
#   POST   /strategies/rl/train             → comprehensive training with run_id tracking
#   GET    /strategies/rl/status            → real-time status and recent runs
#   POST   /strategies/rl/train-walkforward → multi-window walk-forward training
#   POST   /strategies/rl/deploy            → model deployment with executor scheduling
#   GET    /strategies/rl/executor/status   → executor registry snapshot
#   etc.

# This router exists only for backwards compatibility during the cleanup phase.
# It is NOT mounted in main.py and has NO active endpoints.
# See engine/main.py line 596 — only strategies_router is included.
