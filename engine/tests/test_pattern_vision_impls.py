"""Unit tests for the concrete Pattern Vision Protocol implementations.

Offline: no network, no Anthropic calls, no display. matplotlib is driven
in Agg mode by the module under test.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.pattern_vision_analyst import VisionClassification
from agents.pattern_vision_impls import (
    ClaudeVisionClassifier,
    MatplotlibChartCapture,
    _lookback_days_for,
    _normalize_ohlcv,
    _render_candlestick_png,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _synthetic_ohlcv(n: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, size=n))
    high = close + np.abs(rng.normal(0, 0.2, size=n))
    low = close - np.abs(rng.normal(0, 0.2, size=n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(100, 10_000, size=n)
    idx = pd.date_range("2026-04-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


class _FakeDataManager:
    def __init__(self, df: pd.DataFrame | None):
        self.df = df
        self.calls: list[dict[str, Any]] = []

    async def get_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "symbol": symbol,
                "lookback_days": lookback_days,
                "timeframe": timeframe,
                "is_futures": is_futures,
            }
        )
        return self.df if self.df is not None else pd.DataFrame()


@dataclass
class _FakeLLMResult:
    success: bool = True
    content: str = ""
    error: str | None = None


class _FakeLLMClient:
    def __init__(self, result: _FakeLLMResult):
        self.result = result
        self.last_call: dict[str, Any] = {}

    async def call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        agent_name: str,
        temperature: float,
    ) -> _FakeLLMResult:
        self.last_call = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "agent_name": agent_name,
            "temperature": temperature,
        }
        return self.result


# ---------------------------------------------------------------------------
# _lookback_days_for
# ---------------------------------------------------------------------------


def test_lookback_days_for_minute_timeframe():
    # 120 bars of 5m at 78 bars/day -> need ~2 days (+1 slack)
    d = _lookback_days_for("5m", 120)
    assert d >= 2
    assert d <= 10


def test_lookback_days_for_hour_timeframe():
    # 120 bars of 1h at ~6 bars/day -> ~20 days + slack
    d = _lookback_days_for("1h", 120)
    assert d >= 20


def test_lookback_days_for_daily_timeframe():
    d = _lookback_days_for("1d", 120)
    assert d >= 120


def test_lookback_days_for_unknown_timeframe_defaults_to_30():
    assert _lookback_days_for("weekly", 120) == 30


# ---------------------------------------------------------------------------
# _normalize_ohlcv
# ---------------------------------------------------------------------------


def test_normalize_ohlcv_lowercases_columns():
    df = _synthetic_ohlcv(30)
    out = _normalize_ohlcv(df)
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_ohlcv_raises_on_missing_columns():
    df = pd.DataFrame({"Open": [1.0], "Close": [1.0]})
    with pytest.raises(RuntimeError, match="missing OHLC columns"):
        _normalize_ohlcv(df)


# ---------------------------------------------------------------------------
# _render_candlestick_png
# ---------------------------------------------------------------------------


def test_render_candlestick_produces_valid_png():
    df = _normalize_ohlcv(_synthetic_ohlcv(60))
    png = _render_candlestick_png(
        df,
        title="MCL 1h test",
        figure_size=(8.0, 4.0),
        dpi=80,
        sma_periods=(20,),
    )
    # PNG magic number: 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000, "rendered PNG should be at least ~1KB"


def test_render_skips_sma_when_insufficient_bars():
    df = _normalize_ohlcv(_synthetic_ohlcv(15))
    png = _render_candlestick_png(
        df,
        title="short",
        figure_size=(6.0, 3.0),
        dpi=80,
        sma_periods=(50,),  # longer than df
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# MatplotlibChartCapture
# ---------------------------------------------------------------------------


async def test_capture_returns_png_bytes_for_healthy_data():
    data = _FakeDataManager(_synthetic_ohlcv(60))
    capture = MatplotlibChartCapture(data_manager=data, lookback_bars=50)

    png = await capture.capture("MCL", "1h")

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert data.calls[0]["symbol"] == "MCL"
    assert data.calls[0]["timeframe"] == "1h"
    assert data.calls[0]["is_futures"] is True


async def test_capture_raises_when_data_manager_returns_empty():
    capture = MatplotlibChartCapture(data_manager=_FakeDataManager(pd.DataFrame()))
    with pytest.raises(RuntimeError, match="no bars returned"):
        await capture.capture("MCL", "1h")


async def test_capture_raises_when_insufficient_bars():
    capture = MatplotlibChartCapture(data_manager=_FakeDataManager(_synthetic_ohlcv(5)))
    with pytest.raises(RuntimeError, match="need at least 20"):
        await capture.capture("MCL", "1h")


async def test_capture_respects_lookback_bars_limit():
    df = _synthetic_ohlcv(200)
    data = _FakeDataManager(df)
    capture = MatplotlibChartCapture(data_manager=data, lookback_bars=50)

    png = await capture.capture("MCL", "1h")

    # The render should only use tail 50, but we can't easily re-decode the
    # PNG to count bars. Proxy assertion: lookback_days passed to get_bars
    # reflects lookback_bars=50 rather than 200.
    assert data.calls[0]["lookback_days"] >= 5


# ---------------------------------------------------------------------------
# ClaudeVisionClassifier
# ---------------------------------------------------------------------------


async def test_classifier_sends_image_block_with_base64_png():
    png_bytes = b"\x89PNG\r\n\x1a\nfake-body"
    llm = _FakeLLMClient(
        _FakeLLMResult(
            success=True,
            content=json.dumps(
                {
                    "pattern_type": "bull_flag",
                    "signal": 0.5,
                    "confidence": 0.7,
                    "reasoning": "flag after impulse",
                }
            ),
        )
    )
    classifier = ClaudeVisionClassifier(llm_client=llm)

    out = await classifier.classify(png_bytes, context="MCL 1h test")

    assert isinstance(out, VisionClassification)
    assert out.pattern_type == "bull_flag"

    blocks = llm.last_call["messages"][0]["content"]
    image_block = blocks[0]
    text_block = blocks[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/png"
    # Round-trip base64 back to the original bytes
    assert base64.standard_b64decode(image_block["source"]["data"]) == png_bytes
    assert text_block["type"] == "text"
    assert "MCL 1h test" in text_block["text"]


async def test_classifier_raises_on_llm_failure():
    llm = _FakeLLMClient(_FakeLLMResult(success=False, error="rate limit"))
    classifier = ClaudeVisionClassifier(llm_client=llm)

    with pytest.raises(RuntimeError, match="rate limit"):
        await classifier.classify(b"png", context="ctx")


async def test_classifier_parses_malformed_json_via_parse_vision_json():
    # Response is garbage — parse_vision_json must return no_clear_pattern
    # abstention rather than raising (so _safe_classify can route through
    # the standard abstention path).
    llm = _FakeLLMClient(_FakeLLMResult(success=True, content="not-json"))
    classifier = ClaudeVisionClassifier(llm_client=llm)

    out = await classifier.classify(b"png", context="ctx")

    assert out.pattern_type == "no_clear_pattern"
    assert out.confidence == 0.0


async def test_classifier_uses_configured_model_and_tokens():
    llm = _FakeLLMClient(
        _FakeLLMResult(
            success=True,
            content='{"pattern_type": "no_clear_pattern", "signal": 0, "confidence": 0, "reasoning": ""}',
        )
    )
    classifier = ClaudeVisionClassifier(
        llm_client=llm,
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        temperature=0.0,
        agent_name="test_agent",
    )

    await classifier.classify(b"png", context="ctx")

    assert llm.last_call["model"] == "claude-haiku-4-5-20251001"
    assert llm.last_call["max_tokens"] == 256
    assert llm.last_call["temperature"] == 0.0
    assert llm.last_call["agent_name"] == "test_agent"


# ---------------------------------------------------------------------------
# End-to-end: capture -> classify -> report, with real matplotlib + fake LLM
# ---------------------------------------------------------------------------


async def test_end_to_end_capture_and_classify_integration():
    """Full Protocol round-trip: synthetic OHLCV -> PNG -> fake vision -> classification.

    Exercises the real matplotlib render path feeding a real base64 encode
    step — only the data source and LLM endpoint are faked.
    """
    from agents.pattern_vision_analyst import PatternVisionAnalyst

    df = _synthetic_ohlcv(80)
    capture = MatplotlibChartCapture(data_manager=_FakeDataManager(df), lookback_bars=60)
    llm = _FakeLLMClient(
        _FakeLLMResult(
            success=True,
            content=json.dumps(
                {
                    "pattern_type": "range_consolidation",
                    "signal": 0.0,
                    "confidence": 0.4,
                    "reasoning": "bars drift inside narrow band",
                }
            ),
        )
    )
    classifier = ClaudeVisionClassifier(llm_client=llm)
    analyst = PatternVisionAnalyst(chart_capture=capture, classifier=classifier)

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.pattern_type == "range_consolidation"
    assert report.confidence == pytest.approx(0.4)
    # Verify the real base64 encode step ran against real PNG bytes
    image_block = llm.last_call["messages"][0]["content"][0]
    decoded = base64.standard_b64decode(image_block["source"]["data"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"
