"""
JARVIS TRADER — Kronos Financial Foundation Model Classifier (stub)
===================================================================
Wraps the (future) shiyu-coder/Kronos foundation model as the 7th analyst in
the debate pipeline. The paper input schema requires a ``pd.DataFrame`` with
columns ``open``, ``high``, ``low``, ``close`` (``volume`` optional) and a
minimum of ``MIN_BARS`` rows.

``classify()`` is async-compatible (FastAPI-safe) and always returns a plain
``dict`` with keys ``signal``, ``confidence``, ``summary``.

Gated by ``ENABLE_KRONOS`` env var (default off — set to ``"1"`` to activate).
Do NOT add this flag to ``engine/.env.example`` automatically; Amo will do that.

STUB MODE: the real ``KronosPredictor.predict()`` call is not wired. When the
predictor is ready, fill in ``_predict_sync`` only — no other interface change
is needed for callers (``_predict_async`` calls it in an executor, ``classify``
calls ``_predict_async``, ``_forecast_to_verdict`` maps the result to the
contract dict).

See ``docs/runbooks/KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md`` for schema and
calibration notes (confirmed in commit e72ae23).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

KronosBars = pd.DataFrame  # expected columns: open, high, low, close, volume (opt)

# ---------------------------------------------------------------------------
# Environment-flag helper
# ---------------------------------------------------------------------------

_ENV_FLAG = "ENABLE_KRONOS"


def is_kronos_enabled() -> bool:
    """Return True only when ``ENABLE_KRONOS`` is set to the exact string ``"1"``.

    Re-read from ``os.environ`` on every call (no module-level caching) so that
    ``/admin/feature-flags`` toggles take effect without an engine restart.
    The strict equality guards against accidentally-truthy values (``"true"``,
    ``" 1"``, etc.) silently activating a neutral-verdict stub that would dilute
    the debate stack with phantom signal.
    """
    return os.environ.get(_ENV_FLAG, "").strip() == "1"


# ---------------------------------------------------------------------------
# KronosClassifier
# ---------------------------------------------------------------------------


class KronosClassifier:
    """Stub for the shiyu-coder/Kronos foundation model.

    Real implementation fills in ``_predict_sync`` only — callers see no
    interface change because ``classify`` always delegates through
    ``_predict_async`` → ``_predict_sync`` → ``_forecast_to_verdict``.

    Graceful-degradation contract: ``classify`` never raises.
    """

    MIN_BARS: int = 10

    # Per-instrument calibrated thresholds (bps) from calibrate_kronos_threshold.py
    # first-pass commit 22250bb.  Updated 2026-05-20.
    #
    # Callers SHOULD pass ``symbol`` to ``classify()`` for accurate thresholds.
    # A bare ``classify(bars)`` call (symbol=None) uses BULL_BEAR_THRESHOLD_BPS_DEFAULT
    # (63 bps), which is the p75 of the median across calibrated instruments.
    # This is a deliberate behavior change from the pre-refactor stub (which used 20 bps).
    BULL_BEAR_THRESHOLD_BPS_BY_SYMBOL: dict[str, float] = {
        "MES": 48.0,
        "MNQ": 63.0,
        "MCL": 207.0,
    }
    BULL_BEAR_THRESHOLD_BPS_DEFAULT: float = (
        63.0  # global fallback (p75 of median across calibrated instruments)
    )

    def __init__(self, model_name: str = "kronos-mini", lookback: int = 400) -> None:
        self.model_name = model_name
        self.lookback = lookback
        self._predictor = None  # Loaded lazily; stays None in stub mode
        if not is_kronos_enabled():
            logger.debug("[KronosClassifier] ENABLE_KRONOS is not set — stub will return neutral.")

    def _threshold_for(self, symbol: str | None) -> float:
        """Return the calibrated bull/bear threshold (bps) for a given symbol.

        Falls back to ``BULL_BEAR_THRESHOLD_BPS_DEFAULT`` when symbol is None
        or not in the per-instrument table.
        """
        if symbol is None:
            return self.BULL_BEAR_THRESHOLD_BPS_DEFAULT
        return self.BULL_BEAR_THRESHOLD_BPS_BY_SYMBOL.get(
            symbol, self.BULL_BEAR_THRESHOLD_BPS_DEFAULT
        )

    async def classify(self, bars: KronosBars, symbol: str | None = None) -> dict:
        """Classify an OHLC(V) DataFrame.  Always returns a dict.

        Args:
            bars:   ``pd.DataFrame`` with at minimum columns
                    ``open``, ``high``, ``low``, ``close`` and ``MIN_BARS`` rows.
                    ``volume`` is accepted but not required.
            symbol: Instrument symbol (e.g. ``"MES"``, ``"MNQ"``, ``"MCL"``) used
                    to select the per-instrument calibrated threshold.  When
                    ``None`` the global default (63 bps) is used.  Callers should
                    always pass the symbol for accurate threshold selection.

        Returns:
            ``{"signal": float, "confidence": float, "summary": str}``

            * ``signal`` — ``[-1.0, +1.0]`` (negative = bearish, positive = bullish)
            * ``confidence`` — ``[0.0, 1.0]``
            * ``summary`` — human-readable explanation for debate-stack logging

        Note on backward compatibility:
            Before this refactor the threshold was a hard-coded class constant of
            20 bps.  Callers that pass no ``symbol`` now receive the 63-bps default
            instead of 20 bps — a deliberate tightening that reduces false signals
            on uncalibrated instruments.
        """
        if not isinstance(bars, pd.DataFrame):
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "bars not DataFrame",
            }
        if len(bars) < self.MIN_BARS:
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": f"need >={self.MIN_BARS} bars, got {len(bars)}",
            }
        for col in ("open", "high", "low", "close"):
            if col not in bars.columns:
                return {
                    "signal": 0.0,
                    "confidence": 0.0,
                    "summary": f"missing column {col}",
                }

        # Delegate through the async wrapper so the FastAPI event loop is not blocked
        # when the real predictor is wired.
        forecast = await self._predict_async(bars)
        return self._forecast_to_verdict(forecast, bars, symbol)

    async def _predict_async(self, bars: KronosBars) -> Optional[pd.DataFrame]:
        """Run the synchronous predictor in an executor to avoid blocking the loop.

        Stub returns ``None``.  Real implementation::

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._predict_sync, bars)
        """
        return None  # stub — no predictor loaded

    def _predict_sync(self, bars: KronosBars) -> pd.DataFrame:
        """Synchronous wrapper around ``KronosPredictor.predict()``.

        Stub raises ``NotImplementedError``.  Real implementation calls the
        predictor and returns a forecast DataFrame with the same OHLC schema.
        """
        raise NotImplementedError("Kronos predictor not loaded; this is a stub")

    def _forecast_to_verdict(
        self,
        forecast: Optional[pd.DataFrame],
        bars: KronosBars,
        symbol: str | None = None,
    ) -> dict:
        """Map a forecast DataFrame to the contract dict.

        When ``forecast`` is ``None`` (stub or load failure) the method returns
        a neutral dict so ``_predict_async`` returning ``None`` is safe.

        Signal derivation:
          * Compute predicted return in basis points vs. last observed close.
          * Threshold is instrument-specific via ``_threshold_for(symbol)``.
          * If ``abs(ret_bps) <= threshold`` -> neutral (signal=0).
          * Otherwise scale linearly, clamped to ``[-1.0, +1.0]``.
        Confidence proxy (until MC sample_count > 1 is wired):
          * ``min(1.0, abs(ret_bps) / (5 * threshold))``
        """
        if forecast is None:
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "stub — predictor not wired",
            }

        threshold = self._threshold_for(symbol)
        last_close = float(bars["close"].iloc[-1])
        pred_close = float(forecast["close"].iloc[-1])
        ret_bps = (pred_close - last_close) / last_close * 10_000

        scale = 5.0 * threshold
        if ret_bps > threshold:
            signal = min(1.0, ret_bps / scale)
        elif ret_bps < -threshold:
            signal = max(-1.0, ret_bps / scale)
        else:
            signal = 0.0

        confidence = min(1.0, abs(ret_bps) / scale)

        return {
            "signal": signal,
            "confidence": confidence,
            "summary": f"predicted {ret_bps:+.1f} bps over {len(forecast)} bars",
        }


# ---------------------------------------------------------------------------
# NEXT STEPS (live-wiring follow-up — not in scope for this stub)
# ---------------------------------------------------------------------------
# 1. Implement _predict_sync to call KronosPredictor.predict(bars).
#    The paper requires pd.DataFrame input (confirmed e72ae23); no HF endpoint.
# 2. Wire MC rollout sample_count > 1 into _forecast_to_verdict confidence.
# 3. Per-instrument thresholds already calibrated (commit 22250bb); expand table
#    when new instruments are added (see BULL_BEAR_THRESHOLD_BPS_BY_SYMBOL).
# 4. Add ENABLE_KRONOS= to engine/.env.example (Amo does this step).
