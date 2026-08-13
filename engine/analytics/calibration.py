"""
JARVIS TRADER -- Fitted signal->probability calibration curve
================================================================
Completes the second half of roadmap-drain task MR-1.1's proof line: the
inverted-Brier fix (``ic_ensemble.score_forecast``, commit 890ad09) made the
scoring rule *proper* using a linear map ``p = (signal + 1) / 2``. That
docstring explicitly names a fitted curve as "the natural next refinement" --
this module is that refinement: an isotonic (monotonic, non-parametric)
regression of realized outcome against signal, fit on an agent's own
historical (signal, pnl) pairs.

POINT-IN-TIME DISCIPLINE (see ../../.claude/rules/testing.md "No look-ahead
bias") -- read before wiring this anywhere new
---------------------------------------------------------------------------
A curve fit on a window of trades and then used to *rescore those same
trades* is in-sample: the resulting Brier average would be artificially good,
a self-fulfilling metric of exactly the kind this project has been burned by
before (DSR contamination, the honest-data-drain correction). This module is
therefore deliberately NOT wired into ``BrierCalibrationTracker.compute_brier``
/ ``compute_rolling_brier`` -- those remain the simple, honest linear map,
unchanged, still the only inputs to the live ``/health.brier_30d_rolling``
field the real-money-readiness gate reads. ``fit_isotonic_calibration`` is a
standalone, additive capability meant only for *prospective* use: fit once on
history, then score a NEW incoming signal whose outcome the fit could not
have seen. Any future wiring into a live scoring/weighting path is itself a
live debate-stage-trust change and needs the same Tier-3 review as MR-1.1
overall -- do not wire it in "for free" alongside an unrelated change.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # sklearn is already pulled in transitively (RL stack); mirror the
    # project's existing lazy-optional-dependency pattern (see ic_ensemble's
    # scipy import) rather than assuming it's always present.
    from sklearn.isotonic import IsotonicRegression  # type: ignore

    _HAS_SKLEARN = True
except Exception:  # pragma: no cover - sklearn optional
    _HAS_SKLEARN = False
    logger.info("sklearn not available; fit_isotonic_calibration will no-op.")

__all__ = ["fit_isotonic_calibration", "MIN_SAMPLES_FOR_CALIBRATION_FIT"]


# An isotonic fit with too few points degenerates into a step function that
# memorizes each individual outcome rather than a real calibration curve --
# MIN_TRADES_FOR_IC=5 (ic_ensemble.py) is enough to trust a rank correlation's
# *sign*, but a monotone regression needs enough points spread across the
# signal range to have more than one step between neighbors. 15 mirrors the
# project's existing evidence-floor style (FULL_CONFIDENCE_TRADES's SE-based
# reasoning in ic_ensemble.py) without requiring a full 40-trade history.
MIN_SAMPLES_FOR_CALIBRATION_FIT = 15


def fit_isotonic_calibration(
    pairs: List[Tuple[float, float]],
    min_samples: int = MIN_SAMPLES_FOR_CALIBRATION_FIT,
) -> Optional[Callable[[float], float]]:
    """Fit a monotonic signal->P(up-move) curve on historical (signal, pnl) pairs.

    Returns ``None`` (never raises) when sklearn is unavailable or there is
    insufficient history -- callers must fall back to the linear map in that
    case, exactly as ``BrierCalibrationTracker`` already does for a cold-start
    agent via ``BRIER_NEUTRAL``.

    The returned callable clips its input to [-1, 1] and its output to [0, 1],
    matching ``score_forecast``'s existing contract so callers can swap one
    for the other without changing anything downstream.
    """
    if not _HAS_SKLEARN or len(pairs) < min_samples:
        return None

    signals = [max(-1.0, min(1.0, s)) for s, _pnl in pairs]
    outcomes = [1.0 if pnl > 0 else 0.0 for _s, pnl in pairs]

    # Degenerate inputs (all-one-outcome, all-one-signal) make isotonic fits
    # either meaningless or liable to raise inside sklearn -- fail closed to
    # the linear fallback rather than returning a curve that's really just a
    # constant.
    if len(set(outcomes)) < 2 or len(set(signals)) < 2:
        return None

    try:
        model = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        model.fit(signals, outcomes)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("isotonic calibration fit failed: %s", exc)
        return None

    def _predict(signal: float) -> float:
        clipped = max(-1.0, min(1.0, signal))
        try:
            value = float(model.predict([clipped])[0])
        except Exception:  # pragma: no cover - defensive
            return (clipped + 1.0) / 2.0
        return max(0.0, min(1.0, value))

    return _predict
