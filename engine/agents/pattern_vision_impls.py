"""
Concrete Protocol implementations for the Pattern Vision Analyst.

The scaffold in ``pattern_vision_analyst.py`` declares two Protocols —
``ChartCapture`` and ``VisionClassifier`` — so the orchestration layer can
be unit-tested without Chrome or the Anthropic API. This module provides
the engine-runtime bindings.

Design choice: render charts with **matplotlib** rather than the
``chrome-devtools`` MCP. The MCP is a Claude-Code-agent tool, spoken over
stdio from an interactive session; the engine is a long-running FastAPI
process and cannot practically drive an MCP subprocess per analyst call.
matplotlib is already installed (3.10.8 as of 2026-04-17), produces
deterministic output, and needs no browser. The vision classifier does
not care whether the candlesticks came from TradingView or matplotlib —
it's looking at shapes.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Any, Protocol

import pandas as pd

from agents.pattern_vision_analyst import (
    VisionClassification,
    parse_vision_json,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chart capture — matplotlib candlestick renderer
# ---------------------------------------------------------------------------


class _DataManagerProto(Protocol):
    async def get_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: str = "5m",
        is_futures: bool = False,
    ) -> pd.DataFrame: ...


class MatplotlibChartCapture:
    """Render OHLCV bars as a candlestick chart PNG.

    Uses ``data_manager.get_bars`` (same waterfall as TechnicalAnalyst:
    IBKR -> Polygon -> CSV cache). Returns PNG bytes ready for the
    Anthropic vision API. Raises ``RuntimeError`` on insufficient data so
    the analyst's ``_safe_capture`` wrapper routes through the standard
    abstention path.
    """

    def __init__(
        self,
        data_manager: _DataManagerProto,
        *,
        lookback_bars: int = 120,
        figure_size: tuple[float, float] = (12.0, 6.0),
        dpi: int = 100,
        sma_periods: tuple[int, ...] = (20, 50),
    ) -> None:
        self._data = data_manager
        self._lookback_bars = lookback_bars
        self._figure_size = figure_size
        self._dpi = dpi
        self._sma_periods = sma_periods

    async def capture(self, symbol: str, timeframe: str) -> bytes:
        lookback_days = _lookback_days_for(timeframe, self._lookback_bars)
        df = await self._data.get_bars(
            symbol=symbol,
            lookback_days=lookback_days,
            timeframe=timeframe,
            is_futures=True,
        )
        if df is None or df.empty:
            raise RuntimeError(f"no bars returned for {symbol} {timeframe}")

        df = _normalize_ohlcv(df).tail(self._lookback_bars)
        if len(df) < 20:
            raise RuntimeError(
                f"only {len(df)} bars after normalization for {symbol} {timeframe} — "
                "need at least 20 to render a meaningful chart"
            )

        return await asyncio.to_thread(
            _render_candlestick_png,
            df,
            title=f"{symbol} {timeframe} ({len(df)} bars)",
            figure_size=self._figure_size,
            dpi=self._dpi,
            sma_periods=self._sma_periods,
        )


def _lookback_days_for(timeframe: str, bars: int) -> int:
    """How many calendar days of bars do we need to confidently hit `bars`?

    Uses 6.5 market hours/day for intraday bars. Over-estimates rather than
    under to let the market-data waterfall trim back to the desired window.
    """
    tf = timeframe.lower()
    if tf.endswith("m"):
        try:
            minutes = int(tf[:-1])
        except ValueError:
            minutes = 5
        bars_per_day = max(1, int(6.5 * 60 // minutes))
        return max(2, (bars // bars_per_day) + 1)
    if tf.endswith("h"):
        try:
            hours = int(tf[:-1])
        except ValueError:
            hours = 1
        bars_per_day = max(1, int(6.5 // hours))
        return max(5, (bars // bars_per_day) + 2)
    if tf.endswith("d"):
        return max(bars + 10, 30)
    return 30


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(out.columns)
    if missing:
        raise RuntimeError(f"missing OHLC columns: {sorted(missing)}")
    return out


def _render_candlestick_png(
    df: pd.DataFrame,
    *,
    title: str,
    figure_size: tuple[float, float],
    dpi: int,
    sma_periods: tuple[int, ...],
) -> bytes:
    """Return PNG bytes for a candlestick chart of `df`.

    Uses the Agg backend explicitly — the engine runs as a FastAPI server
    with no display, and leaving backend selection implicit has caused
    past ``TclError: no display name`` failures on headless boxes.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    # Figure() object API (not pyplot) so this render is thread-safe under
    # asyncio.to_thread: pyplot's global figure registry is process-wide shared
    # state that races across concurrent renders. An explicit Agg canvas keeps
    # it headless and version-independent for savefig.
    fig = Figure(figsize=figure_size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    try:
        xs = range(len(df))
        wick_width = 0.08
        body_width = 0.6

        for i, (_, row) in enumerate(df.iterrows()):
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]  # noqa: E741  # OHLC convention
            up = c >= o
            color = "#2ca02c" if up else "#d62728"
            ax.add_patch(
                Rectangle(
                    (i - body_width / 2, min(o, c)),
                    body_width,
                    max(abs(c - o), 1e-9),
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.5,
                )
            )
            ax.add_line(
                Line2D(
                    [i, i],
                    [l, h],
                    color=color,
                    linewidth=wick_width * 10,
                    solid_capstyle="butt",
                )
            )

        plotted_sma = 0
        for period in sma_periods:
            if len(df) >= period:
                sma = df["close"].rolling(period).mean()
                ax.plot(list(xs), list(sma), linewidth=1.0, label=f"SMA{period}", alpha=0.7)
                plotted_sma += 1

        ax.set_title(title)
        ax.set_xlim(-1, len(df))
        ax.grid(True, alpha=0.2)
        if plotted_sma:
            ax.legend(loc="upper left", fontsize=8)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        return buf.getvalue()
    finally:
        # Figure() has no global pyplot registry entry to close.
        del fig


# ---------------------------------------------------------------------------
# Vision classifier — Claude with base64 image blocks
# ---------------------------------------------------------------------------


class _LLMClientProto(Protocol):
    async def call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        agent_name: str,
        temperature: float,
    ) -> Any:
        ...


_VISION_SYSTEM_PROMPT = (
    "You are a chart-pattern-recognition analyst for JARVIS TRADER, an "
    "autonomous futures-trading system. You will receive a candlestick "
    "chart image plus a short context block. Classify the dominant visual "
    "pattern against the provided schema. Respond with JSON only."
)


class ClaudeVisionClassifier:
    """Vision classifier backed by ``LLMClient.call`` with image blocks.

    Model default: ``claude-sonnet-4-6`` — vision capable, reasonable cost
    vs. Opus for pattern recognition. Callers can override per-invocation.
    """

    def __init__(
        self,
        llm_client: _LLMClientProto,
        *,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 512,
        temperature: float = 0.2,
        agent_name: str = "pattern_vision_analyst",
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._agent_name = agent_name

    async def classify(self, png_bytes: bytes, context: str) -> VisionClassification:
        b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": context},
                ],
            }
        ]

        result = await self._llm.call(
            model=self._model,
            system=_VISION_SYSTEM_PROMPT,
            messages=messages,
            max_tokens=self._max_tokens,
            agent_name=self._agent_name,
            temperature=self._temperature,
        )
        if not getattr(result, "success", False):
            err = getattr(result, "error", "unknown")
            raise RuntimeError(f"vision LLM call failed: {err}")

        return parse_vision_json(getattr(result, "content", "") or "")
