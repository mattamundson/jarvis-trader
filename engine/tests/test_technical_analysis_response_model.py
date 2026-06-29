"""Regression: TechnicalAnalysisResponse.signal must accept the analyst's numeric
signal (a float).

The TechnicalAnalyst report dataclass declares ``signal: float`` and always sets it
numerically (``float(result.get("signal", 0.0))``). The response model previously
typed it ``str``, so ``POST /analyze/technical`` 500'd with a
ResponseValidationError — ``{'loc': ('response','signal'), 'msg': 'Input should be
a valid string', 'input': 0.2}`` — breaking the dashboard chart's technical overlay
on every load.
"""

from __future__ import annotations

from api.models import TechnicalAnalysisResponse


def _payload(signal):
    # Mirrors routers/analysis_router.py::run_technical_analysis() return shape.
    return {
        "symbol": "MES",
        "timestamp": "2026-06-22T16:00:00+00:00",
        "timeframe": "15m",
        "signal": signal,
        "confidence": 0.7,
        "trend": "up",
        "regime": "trend",
        "is_overbought": False,
        "is_oversold": False,
        "summary": "ok",
        "reasoning": "because",
        "scores": {"trend": 0.2},
        "levels": {"current_price": 5300.0},
        "raw_indicators": {"ema_8": 5300.0},
    }


def test_accepts_float_signal():
    m = TechnicalAnalysisResponse(**_payload(0.2))
    assert m.signal == 0.2
    assert isinstance(m.signal, float)


def test_accepts_zero_neutral_signal():
    m = TechnicalAnalysisResponse(**_payload(0.0))
    assert m.signal == 0.0


def test_round_trips_through_json():
    import json

    m = TechnicalAnalysisResponse(**_payload(-0.85))
    assert json.loads(m.model_dump_json())["signal"] == -0.85
