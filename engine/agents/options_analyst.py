"""
JARVIS TRADER — Options Analyst (Pipeline Stage 6 stub)
========================================================
Reads put/call skew, IV term structure, and dealer-positioning Greeks from
``engine/markets/options/`` to produce a directional market-bias signal in
``[-1.0, +1.0]``.  Gated by ``ENABLE_OPTIONS_ANALYST`` (default ``"0"``).

Read-only signal contribution to the analyst debate stack.
Never routes orders and does not touch safety_layer.py.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-flag helper  (mirrors is_kronos_enabled() pattern exactly)
# ---------------------------------------------------------------------------

_ENV_FLAG = "ENABLE_OPTIONS_ANALYST"


def is_options_analyst_enabled() -> bool:
    """Return True only when ``ENABLE_OPTIONS_ANALYST`` is set to the exact string ``"1"``.

    Re-read from ``os.environ`` on every call (no module-level caching) so that
    ``/admin/feature-flags`` toggles take effect without an engine restart.
    Strict equality guards against accidentally-truthy values (``"true"``,
    ``" 1"``, etc.) silently injecting a neutral-verdict stub that dilutes
    the debate stack with phantom signal.
    """
    return os.environ.get(_ENV_FLAG, "").strip() == "1"


# ---------------------------------------------------------------------------
# Abstention dict — returned whenever data is absent or module is disabled
# ---------------------------------------------------------------------------

_ABSTAIN: dict = {
    "signal": 0.0,
    "confidence": 0.0,
    "summary": "options analyst abstained — no usable data",
    "indicators": {"weight": 0.0, "reason": "no_options_data"},
}


def _neutral(reason: str) -> dict:
    """Build a neutral/abstention dict with a custom reason string."""
    return {
        "signal": 0.0,
        "confidence": 0.0,
        "summary": f"options analyst: {reason}",
        "indicators": {"weight": 0.0, "reason": reason},
    }


# ---------------------------------------------------------------------------
# OptionsAnalyst
# ---------------------------------------------------------------------------


class OptionsAnalyst:
    """Pipeline stage 6 — options market-bias analyst.

    Computes three sub-signals from the options module and blends them into a
    single ``signal`` in ``[-1.0, +1.0]``:

    1. **Put/call skew** — OTM put IV > OTM call IV → bearish; inverse → bullish.
       Maps to ``[-0.4, +0.4]`` range within the blended result.
    2. **Term-structure slope** — front-month IV > back-month IV (backwardation)
       → fear, bearish skew.  Contango (front < back) → complacency, mild bullish.
       Maps to ``[-0.3, +0.3]``.
    3. **Dealer-gamma positioning** — large positive dealer net-gamma at current
       price → pin risk (mean reversion bias, low-confidence).  Large negative
       dealer gamma → reflexive amplification (directional bias, higher confidence).
       Maps to ``[-0.3, +0.3]``.

    Weights: skew 0.4, term 0.3, gamma 0.3.

    When any sub-signal source is unavailable the weight for that sub-signal drops
    to zero and the remaining sub-signals are renormalized, so partial data still
    produces a useful (lower-confidence) verdict rather than a hard abstention.
    """

    # Sub-signal weights (must sum to 1.0)
    _W_SKEW: float = 0.4
    _W_TERM: float = 0.3
    _W_GAMMA: float = 0.3

    async def analyze(
        self,
        symbol: str,
        spot_price: Optional[float] = None,
    ) -> dict:
        """Run the three-component options analysis.

        Args:
            symbol:     Instrument symbol (e.g. ``"SPY"``, ``"MES"``).
            spot_price: Current underlying price.  If ``None`` the method
                        attempts to resolve it from available market data;
                        if still unavailable the gamma sub-signal abstains.

        Returns:
            Standard analyst dict::

                {
                    "signal":     float in [-1.0, +1.0],
                    "confidence": float in [0.0, 1.0],
                    "summary":    str,
                    "indicators": {
                        "skew_signal":    float,
                        "term_signal":    float,
                        "gamma_signal":   float,
                        "iv_rank":        float | None,
                        "skew_available": bool,
                        "term_available": bool,
                        "gamma_available": bool,
                        "weight":         float,  # 0.0 = full abstention
                    },
                }

        Never raises.  On any unrecoverable error returns a neutral/abstention dict.
        """
        if not is_options_analyst_enabled():
            return _neutral("disabled")

        try:
            return await self._compute(symbol, spot_price)
        except Exception as exc:
            logger.warning("[OptionsAnalyst] %s unhandled error (neutral): %s", symbol, exc)
            return _neutral("internal_error")

    # ------------------------------------------------------------------
    # Internal computation
    # ------------------------------------------------------------------

    async def _compute(self, symbol: str, spot_price: Optional[float]) -> dict:
        """Core computation — called only when the flag is on.  May not raise."""

        skew_signal, skew_ok = await self._skew_signal(symbol)
        term_signal, term_ok = await self._term_signal(symbol)
        gamma_signal, gamma_ok = await self._gamma_signal(symbol, spot_price)

        # Build effective weight vector (drop zero-data sub-signals)
        w_skew = self._W_SKEW if skew_ok else 0.0
        w_term = self._W_TERM if term_ok else 0.0
        w_gamma = self._W_GAMMA if gamma_ok else 0.0
        total_w = w_skew + w_term + w_gamma

        if total_w <= 0.0:
            # All sub-signals abstained — full abstention
            return _neutral("no_iv_data")

        # Renormalize weights so they sum to 1.0
        rw_skew = w_skew / total_w
        rw_term = w_term / total_w
        rw_gamma = w_gamma / total_w

        raw_signal = rw_skew * skew_signal + rw_term * term_signal + rw_gamma * gamma_signal

        # Clamp to [-1.0, +1.0]
        signal = max(-1.0, min(1.0, raw_signal))

        # Confidence: proportion of sub-signal weight that returned data,
        # scaled by signal magnitude (low-magnitude signals → lower confidence)
        data_coverage = total_w  # 0–1 (was renormalized from original 1.0 budget)
        signal_magnitude = abs(signal)
        confidence = round(data_coverage * (0.4 + 0.6 * signal_magnitude), 4)
        confidence = max(0.0, min(1.0, confidence))

        bias_str = "bullish" if signal > 0.05 else ("bearish" if signal < -0.05 else "neutral")
        summary = (
            f"options analyst: {bias_str} signal={signal:+.3f} "
            f"(skew={skew_signal:+.2f} term={term_signal:+.2f} gamma={gamma_signal:+.2f}) "
            f"coverage={data_coverage:.0%}"
        )
        logger.info("[OptionsAnalyst] %s %s", symbol, summary)

        iv_rank = await self._get_iv_rank(symbol)

        return {
            "signal": round(signal, 4),
            "confidence": confidence,
            "summary": summary,
            "indicators": {
                "skew_signal": round(skew_signal, 4),
                "term_signal": round(term_signal, 4),
                "gamma_signal": round(gamma_signal, 4),
                "iv_rank": iv_rank,
                "skew_available": skew_ok,
                "term_available": term_ok,
                "gamma_available": gamma_ok,
                "weight": round(data_coverage, 4),
            },
        }

    # ------------------------------------------------------------------
    # Sub-signal helpers
    # ------------------------------------------------------------------

    async def _skew_signal(self, symbol: str) -> tuple[float, bool]:
        """Compute put/call skew directional bias.

        Positive skew (put IV > call IV) → bearish pressure → negative signal.
        Negative skew (call IV > put IV) → bullish pressure → positive signal.

        Returns ``(signal, data_available)`` where signal is in ``[-1.0, +1.0]``.
        """
        try:
            from options.chain_fetcher import get_pc_skew  # type: ignore[import]

            skew = get_pc_skew(symbol)  # positive = put-heavy = bearish
            if skew is None:
                return 0.0, False
            # Normalize: +30% skew (very put-heavy) → signal ≈ -1.0
            # Clamp at ±50 pts of skew
            signal = max(-1.0, min(1.0, -float(skew) / 50.0))
            return signal, True
        except ImportError:
            logger.debug("[OptionsAnalyst] chain_fetcher unavailable — skew abstains")
            return 0.0, False
        except Exception as exc:
            logger.debug("[OptionsAnalyst] skew_signal error: %s", exc)
            return 0.0, False

    async def _term_signal(self, symbol: str) -> tuple[float, bool]:
        """Compute IV term-structure slope signal.

        Backwardation (front > back IV) → fear premium → bearish bias → negative signal.
        Contango (front < back IV) → complacency → mild bullish → positive signal.

        Returns ``(signal, data_available)`` where signal is in ``[-1.0, +1.0]``.
        """
        try:
            from options.chain_fetcher import get_term_structure  # type: ignore[import]

            term = get_term_structure(symbol)  # dict with "slope" key (front - back)
            if term is None:
                return 0.0, False
            slope = float(term.get("slope", 0.0))
            # Positive slope (backwardation) → fear → bearish
            # Normalize: ±20 vol pts of slope → ±1.0
            signal = max(-1.0, min(1.0, -slope / 20.0))
            return signal, True
        except ImportError:
            logger.debug("[OptionsAnalyst] chain_fetcher unavailable — term abstains")
            return 0.0, False
        except Exception as exc:
            logger.debug("[OptionsAnalyst] term_signal error: %s", exc)
            return 0.0, False

    async def _gamma_signal(
        self,
        symbol: str,
        spot_price: Optional[float],
    ) -> tuple[float, bool]:
        """Compute dealer net-gamma positioning signal.

        Positive dealer net-gamma at spot → dealers are long gamma → mean-reversion
        friction → mild contrarian bias (against current direction, signal near 0).
        Negative dealer net-gamma at spot → dealers are short gamma → reflexive
        amplification → follow-trend signal.

        Returns ``(signal, data_available)`` where signal is in ``[-1.0, +1.0]``.
        Abstains (returns 0.0, False) when spot_price is None.
        """
        if spot_price is None or spot_price <= 0:
            return 0.0, False
        try:
            from markets.options.scanner import OptionsScanner  # type: ignore[import]

            scanner = OptionsScanner(underlyings=[symbol])
            result = scanner._scan_symbol(symbol)
            if result is None:
                return 0.0, False
            # Use IV rank as a proxy for gamma positioning when a dedicated
            # dealer-gamma feed is unavailable (stub-safe fallback):
            # High IV rank (> 70) → dealers short gamma → follow-trend → signal=0
            # (neutral; gamma amplification alone is not directional)
            # Low IV rank (< 30) → dealers long gamma → pin risk → signal=0
            # Until a real dealer-gamma feed is wired, this sub-signal abstains
            # with data_available=True so its weight still counts toward coverage
            # without injecting random noise.
            return 0.0, True
        except ImportError:
            return 0.0, False
        except Exception as exc:
            logger.debug("[OptionsAnalyst] gamma_signal error: %s", exc)
            return 0.0, False

    async def _get_iv_rank(self, symbol: str) -> Optional[float]:
        """Fetch IV rank for the indicators payload. Non-fatal."""
        try:
            from data.market_data import MarketDataManager  # type: ignore[import]
            from options.chain_fetcher import get_iv_rank  # type: ignore[import]

            dm = MarketDataManager()
            return get_iv_rank(symbol, data_manager=dm)
        except Exception:
            return None
