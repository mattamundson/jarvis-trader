"""
JARVIS TRADER — Kronos Financial Foundation Model Classifier
============================================================
Wraps the shiyu-coder/Kronos foundation model as the 7th analyst in
the debate pipeline. The paper input schema requires a ``pd.DataFrame`` with
columns ``open``, ``high``, ``low``, ``close`` (``volume`` optional) and a
minimum of ``MIN_BARS`` rows.

``classify()`` is async-compatible (FastAPI-safe) and always returns a plain
``dict`` with keys ``signal``, ``confidence``, ``summary``.

Gated by ``ENABLE_KRONOS`` env var (default off — set to ``"1"`` to activate).
Do NOT add this flag to ``engine/.env.example`` automatically; Amo will do that.

REAL PREDICTOR: ``_predict_sync`` calls ``KronosPredictor.predict()`` when the
Kronos package is installed (``engine/requirements-kronos.txt``).  If the
package is not importable, a module-level import guard catches the error and
``_predict_sync`` returns ``None`` — the engine boots cleanly without it and
the debate stack receives ``confidence=0.0`` (graceful skip).

No other interface change is needed for callers — ``_predict_async`` calls
``_predict_sync`` in an executor, ``classify`` calls ``_predict_async``, and
``_forecast_to_verdict`` maps the result to the contract dict.

See ``docs/runbooks/KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md`` for schema and
calibration notes (confirmed in commit e72ae23).

Install note:
    The Kronos repo (github.com/shiyu-coder/Kronos) does not publish a pip
    package.  Install via ``pip install -r engine/requirements-kronos.txt``
    which clones and installs from the repo.  See that file for details.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of KronosPredictor — optional dependency
# ---------------------------------------------------------------------------
# The Kronos package is not part of requirements-core.txt.  We attempt the
# import once at module load time and fall back gracefully if it fails.
# This means the engine starts cleanly even without Kronos installed, and
# _predict_sync returns None (neutral) instead of raising.

_KRONOS_AVAILABLE: bool = False
_KronosModelClass = None  # Kronos model class (from model module)
_KronosTokenizerClass = None  # KronosTokenizer class
_KronosPredictorClass = None  # KronosPredictor class

try:
    from model import Kronos as _KronosModelClass  # type: ignore[import-not-found]
    from model import KronosPredictor as _KronosPredictorClass  # type: ignore[import-not-found]
    from model import KronosTokenizer as _KronosTokenizerClass  # type: ignore[import-not-found]

    _KRONOS_AVAILABLE = True
    logger.debug("[KronosClassifier] Kronos package imported successfully.")
except ImportError as _e:
    logger.warning(
        "[KronosClassifier] Kronos package not installed — running in graceful fallback mode. "
        "Install via 'pip install -r engine/requirements-kronos.txt' to enable real inference. "
        "Error: %s",
        _e,
    )

# ---------------------------------------------------------------------------
# Module-level singleton predictor cache
# ---------------------------------------------------------------------------
# Loaded once on first _predict_sync call; shared across all KronosClassifier
# instances (model weights are hundreds of MB — never load per-instance).

_PREDICTOR_SINGLETON: Optional[object] = None  # type: ignore[assignment]
_PREDICTOR_MODEL_PATH: Optional[str] = None  # tracks which path is cached


def _get_or_load_predictor(
    model_path: str,
    tokenizer_path: str,
    max_context: int = 512,
) -> Optional[object]:
    """Return the module-level singleton predictor, loading it on first call.

    Returns ``None`` when the Kronos package is not installed so callers can
    fall through to the neutral-stub path without raising.
    """
    global _PREDICTOR_SINGLETON, _PREDICTOR_MODEL_PATH

    if not _KRONOS_AVAILABLE:
        return None

    if _PREDICTOR_SINGLETON is not None and _PREDICTOR_MODEL_PATH == model_path:
        return _PREDICTOR_SINGLETON

    logger.info(
        "[KronosClassifier] Loading Kronos weights from '%s' (tokenizer: '%s'). "
        "This may take 30–120s on first load.",
        model_path,
        tokenizer_path,
    )
    try:
        tokenizer = _KronosTokenizerClass.from_pretrained(tokenizer_path)  # type: ignore[union-attr]
        model = _KronosModelClass.from_pretrained(model_path)  # type: ignore[union-attr]
        predictor = _KronosPredictorClass(model, tokenizer, max_context=max_context)  # type: ignore[union-attr]
        _PREDICTOR_SINGLETON = predictor
        _PREDICTOR_MODEL_PATH = model_path
        logger.info("[KronosClassifier] Kronos predictor loaded and cached (singleton).")
        return _PREDICTOR_SINGLETON
    except Exception as exc:  # pragma: no cover — load errors are environment-specific
        logger.error(
            "[KronosClassifier] Failed to load Kronos predictor from '%s': %s. "
            "Falling back to neutral.",
            model_path,
            exc,
        )
        return None


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
    """Kronos financial foundation model classifier.

    When the Kronos package is installed (``engine/requirements-kronos.txt``),
    ``_predict_sync`` loads ``KronosPredictor`` from HuggingFace Hub on first
    call (cached as a module-level singleton) and returns a forecast DataFrame.
    When the package is absent, ``_predict_sync`` returns ``None`` and
    ``classify`` emits a neutral verdict — the engine degrades gracefully.

    ``classify`` never raises.  All callers see the same interface regardless
    of whether the Kronos package is installed.
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

    def __init__(
        self,
        model_path: str = "NeoQuasar/Kronos-mini",
        tokenizer_path: str = "NeoQuasar/Kronos-Tokenizer-2k",
        horizon_bars: int = 5,
        lookback: int = 400,
        max_context: int = 512,
    ) -> None:
        """Initialise the classifier.

        Args:
            model_path:     HuggingFace Hub model ID (default: Kronos-mini).
            tokenizer_path: HuggingFace Hub tokenizer ID matching the model.
            horizon_bars:   Number of future bars to forecast (pred_len).
            lookback:       Number of historical bars to feed the predictor.
                            Recommended 400; max 512 for mini, 512 for small/base.
            max_context:    KronosPredictor max_context arg; defaults to 512.
        """
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.horizon_bars = horizon_bars
        self.lookback = lookback
        self.max_context = max_context
        if not is_kronos_enabled():
            logger.debug("[KronosClassifier] ENABLE_KRONOS is not set — will return neutral.")

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
        if not is_kronos_enabled():
            return {"signal": 0.0, "confidence": 0.0, "summary": "stub — ENABLE_KRONOS not set"}

        # Delegate through the async wrapper so the FastAPI event loop is not blocked
        # when the real predictor is wired.
        forecast = await self._predict_async(bars)
        return self._forecast_to_verdict(forecast, bars, symbol)

    async def _predict_async(self, bars: KronosBars) -> Optional[pd.DataFrame]:
        """Run the synchronous predictor in an executor to avoid blocking the loop.

        Wraps ``_predict_sync`` in ``run_in_executor`` so the FastAPI event
        loop is never blocked during model inference (which is CPU/GPU bound
        and can take several seconds per 400-bar window).

        Returns ``None`` when the predictor is unavailable or ``_predict_sync``
        fails — callers should treat ``None`` as a graceful-skip signal.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._predict_sync, bars)

    def _predict_sync(self, bars: KronosBars) -> Optional[pd.DataFrame]:
        """Synchronous wrapper around ``KronosPredictor.predict()``.

        Returns a forecast ``pd.DataFrame`` with columns ``open``, ``high``,
        ``low``, ``close`` (plus ``volume``/``amount`` when populated by the
        model) indexed by the future ``y_timestamp`` Series.

        Returns ``None`` when:
        - The Kronos package is not installed (``_KRONOS_AVAILABLE`` is False).
        - The predictor singleton fails to load (network/disk errors, OOM).
        - Any unexpected exception during inference.

        The ``None`` return flows to ``_forecast_to_verdict`` which maps it to
        a neutral dict — the engine always degrades gracefully.

        Timestamp construction:
          - ``x_timestamp``: the DatetimeIndex of ``bars`` trimmed to
            ``self.lookback`` bars.  If ``bars`` has a plain RangeIndex, a
            synthetic minutely DatetimeIndex is created so the tokenizer has
            valid timestamps (Kronos requires timestamps but does not use them
            for z-score normalisation — they are used only for position
            embeddings).
          - ``y_timestamp``: ``self.horizon_bars`` future periods generated by
            extending the last observed timestamp with the same inferred
            frequency.
        """
        predictor = _get_or_load_predictor(
            self.model_path,
            self.tokenizer_path,
            self.max_context,
        )
        if predictor is None:
            return None

        try:
            # --- Build the input DataFrame ---------------------------------
            # Kronos expects raw OHLCV — no pre-normalisation.  z-score + clip
            # to [-5,5] is applied internally by KronosPredictor.
            input_df = bars[["open", "high", "low", "close"]].copy()
            if "volume" in bars.columns:
                input_df["volume"] = bars["volume"].values
            if "amount" in bars.columns:
                input_df["amount"] = bars["amount"].values

            # Use the last ``lookback`` bars only
            input_df = input_df.iloc[-self.lookback :]

            # --- Derive timestamps -----------------------------------------
            # Use the DataFrame's index when it is already a DatetimeIndex.
            # Otherwise synthesise a 1-minute frequency index ending at "now"
            # so the positional embeddings are valid and internally consistent.
            # NOTE: timezone-naive timestamps are required — Kronos does not
            # handle tz-aware indices and will raise if passed a tz-aware Series.
            if isinstance(input_df.index, pd.DatetimeIndex):
                x_ts = (
                    input_df.index.tz_localize(None)
                    if input_df.index.tz is not None
                    else input_df.index
                )
                freq = pd.tseries.frequencies.to_offset(pd.infer_freq(x_ts) or "1min")
            else:
                # Synthesise: treat each row as one minute, ending now
                x_ts = pd.date_range(
                    end=pd.Timestamp.utcnow().tz_localize(None),
                    periods=len(input_df),
                    freq="1min",
                )
                freq = pd.tseries.frequencies.to_offset("1min")

            x_timestamp = pd.Series(x_ts)
            y_timestamp = pd.Series(
                pd.date_range(
                    start=x_ts[-1] + freq,
                    periods=self.horizon_bars,
                    freq=freq,
                )
            )

            # --- Run inference -----------------------------------------------
            forecast: pd.DataFrame = predictor.predict(  # type: ignore[union-attr]
                df=input_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=self.horizon_bars,
            )
            return forecast

        except Exception as exc:
            logger.warning(
                "[KronosClassifier] _predict_sync raised %s: %s — returning neutral.",
                type(exc).__name__,
                exc,
            )
            return None

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
                "summary": "stub — predictor not wired",  # package missing or load failed
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
# FOLLOW-UP (pending paper-side validation before live flip)
# ---------------------------------------------------------------------------
# 1. MC confidence: wire sample_count >= 5 into _predict_sync and compute std
#    dev across sample paths; feed into _forecast_to_verdict as confidence proxy.
# 2. Per-instrument thresholds calibrated (commit 22250bb); expand table when
#    new instruments are added (see BULL_BEAR_THRESHOLD_BPS_BY_SYMBOL).
# 3. Add ENABLE_KRONOS=0 to engine/.env.example — Amo does this step.
# 4. Measure wall-clock latency for a 400-bar predict() call on this machine
#    (CPU-only) before enabling in the hot path. See runbook §6 pre-flight.
