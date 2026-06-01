"""Tests for engine/agents/kronos_classifier.py.

Covered:
  - is_kronos_enabled() returns False when env var is absent / non-"1"
  - is_kronos_enabled() returns True when ENABLE_KRONOS="1"
  - classify(pd.DataFrame) returns neutral dict when flag is off
  - classify(pd.DataFrame) returns neutral dict when flag is on (stub mode)
  - classify rejects non-DataFrame input gracefully
  - classify rejects fewer-than-MIN_BARS rows
  - classify rejects DataFrames missing required columns
  - _forecast_to_verdict with a real forecast DataFrame
  - _kronos_or_none property: off → None, on → KronosClassifier, off again → None
  - pipeline._call_agent_analyze_kronos: disabled, enabled, missing data manager

Design:
  - Never touches production .env or any real API.
  - Uses monkeypatch.setenv / monkeypatch.delenv — no permanent env writes.
  - pytest-asyncio in auto mode (asyncio_mode = auto in pyproject.toml).
  - Fixture ``bars_df`` is a 20-row synthetic OHLC DataFrame.
"""

from __future__ import annotations

import pandas as pd
import pytest

_ENV_FLAG = "ENABLE_KRONOS"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def bars_df() -> pd.DataFrame:
    """20-row synthetic OHLCV fixture — passes all classify() guards."""
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(20)],
            "high": [101.0 + i * 0.1 for i in range(20)],
            "low": [99.0 + i * 0.1 for i in range(20)],
            "close": [100.5 + i * 0.1 for i in range(20)],
            "volume": [1000] * 20,
        }
    )


# ---------------------------------------------------------------------------
# is_kronos_enabled() gating tests
# ---------------------------------------------------------------------------


def test_kronos_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag absent -> is_kronos_enabled() is False."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.kronos_classifier import is_kronos_enabled

    assert is_kronos_enabled() is False


def test_kronos_disabled_for_non_one_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values other than '1' (after strip) must not enable Kronos.

    is_kronos_enabled() calls .strip() so bare '1' with leading/trailing
    whitespace IS treated as enabled.  Only non-'1' stripped values are tested here.
    """
    from agents.kronos_classifier import is_kronos_enabled

    for bad_value in ("0", "true", "True", "yes", "on", ""):
        monkeypatch.setenv(_ENV_FLAG, bad_value)
        assert (
            is_kronos_enabled() is False
        ), f"Expected is_kronos_enabled() == False for ENABLE_KRONOS={bad_value!r}"


def test_kronos_enabled_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENABLE_KRONOS='1' -> is_kronos_enabled() is True."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.kronos_classifier import is_kronos_enabled

    assert is_kronos_enabled() is True


# ---------------------------------------------------------------------------
# classify() — DataFrame input, stub returns neutral dict
# ---------------------------------------------------------------------------


async def test_classify_returns_neutral_dict_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    bars_df: pd.DataFrame,
) -> None:
    """Disabled flag: classify(df) returns neutral dict with diagnostic summary."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    result = await clf.classify(bars_df)

    assert isinstance(result, dict)
    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert isinstance(result["summary"], str) and len(result["summary"]) > 0


async def test_classify_returns_neutral_dict_when_enabled_stub(
    monkeypatch: pytest.MonkeyPatch,
    bars_df: pd.DataFrame,
) -> None:
    """Enabled flag, but _predict_sync returns None (package missing / load fail):
    classify(df) must return the neutral stub dict.

    We mock _predict_sync to return None so this test covers the
    stub-fallback path regardless of whether the Kronos weights are
    available in the test environment.
    """
    from unittest.mock import patch

    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    with patch.object(clf, "_predict_sync", return_value=None):
        result = await clf.classify(bars_df)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert (
        "stub" in result["summary"].lower()
    ), f"Expected 'stub' in summary; got: {result['summary']!r}"


# ---------------------------------------------------------------------------
# classify() — input validation / rejection tests
# ---------------------------------------------------------------------------


async def test_classify_rejects_list_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list[dict] input must be rejected gracefully with a diagnostic summary."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    # Pass a list-of-dicts (old stub interface) — must not raise
    result = await clf.classify([{"open": 1, "high": 2, "low": 0, "close": 1}])  # type: ignore[arg-type]

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert (
        "not dataframe" in result["summary"].lower()
    ), f"Expected diagnostic message; got: {result['summary']!r}"


async def test_classify_rejects_fewer_than_min_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DataFrame with fewer than MIN_BARS rows must be rejected."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    tiny_df = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    result = await clf.classify(tiny_df)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert (
        str(clf.MIN_BARS) in result["summary"]
    ), f"Expected MIN_BARS ({clf.MIN_BARS}) in summary; got: {result['summary']!r}"


async def test_classify_rejects_missing_column(
    monkeypatch: pytest.MonkeyPatch,
    bars_df: pd.DataFrame,
) -> None:
    """DataFrame missing a required column (e.g. 'close') must be rejected."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    bad_df = bars_df.drop(columns=["close"])
    result = await clf.classify(bad_df)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert (
        "close" in result["summary"]
    ), f"Expected missing column name in summary; got: {result['summary']!r}"


# ---------------------------------------------------------------------------
# _forecast_to_verdict() — direct unit test with fake forecast DataFrame
# ---------------------------------------------------------------------------


def test_forecast_to_verdict_none_returns_neutral() -> None:
    """_forecast_to_verdict(None, bars) returns neutral dict."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    bars = pd.DataFrame({"close": [100.0] * 15})
    result = clf._forecast_to_verdict(None, bars)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert "stub" in result["summary"].lower()


def test_forecast_to_verdict_bullish_signal() -> None:
    """Large positive predicted return maps to positive signal."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    # Last observed close = 100.0; predicted close = 102.0 → +200 bps
    bars = pd.DataFrame({"close": [100.0] * 15})
    forecast = pd.DataFrame({"close": [102.0] * 5})  # 5-bar forecast
    result = clf._forecast_to_verdict(forecast, bars)

    assert result["signal"] > 0.0, f"Expected positive signal; got {result['signal']}"
    assert result["confidence"] > 0.0
    assert "+200" in result["summary"] or "200" in result["summary"]


def test_forecast_to_verdict_bearish_signal() -> None:
    """Large negative predicted return maps to negative signal."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    bars = pd.DataFrame({"close": [100.0] * 15})
    forecast = pd.DataFrame({"close": [98.0] * 5})  # -200 bps
    result = clf._forecast_to_verdict(forecast, bars)

    assert result["signal"] < 0.0, f"Expected negative signal; got {result['signal']}"
    assert result["confidence"] > 0.0


def test_forecast_to_verdict_neutral_within_threshold() -> None:
    """Return within ±default threshold (63 bps) produces signal=0."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    # 10 bps move — well below the 63-bps default threshold
    bars = pd.DataFrame({"close": [100.0] * 15})
    forecast = pd.DataFrame({"close": [100.10] * 5})
    result = clf._forecast_to_verdict(forecast, bars)

    assert result["signal"] == pytest.approx(0.0)


def test_forecast_to_verdict_signal_clamped() -> None:
    """Signal is clamped to [-1.0, +1.0] regardless of predicted return magnitude."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    # Enormous move (10% = 1000 bps) — should clamp to 1.0
    bars = pd.DataFrame({"close": [100.0] * 15})
    forecast = pd.DataFrame({"close": [110.0] * 5})
    result = clf._forecast_to_verdict(forecast, bars)

    assert result["signal"] == pytest.approx(1.0)
    assert result["confidence"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _kronos_or_none property — lazy-init toggle test
# ---------------------------------------------------------------------------


def test_pipeline_kronos_lazy_init_off_then_on_then_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_kronos_or_none re-evaluates the flag on each access.

    Uses a thin fake that holds the property logic so we avoid instantiating
    the full TradingPipeline (heavy deps, DB, IB connections).
    """
    from agents.kronos_classifier import KronosClassifier, is_kronos_enabled

    class _FakePipeline:
        """Minimal host for the _kronos_or_none property logic."""

        @property
        def _kronos_or_none(self):
            if not is_kronos_enabled():
                self._kronos_cached = None
                return None
            if not hasattr(self, "_kronos_cached") or self._kronos_cached is None:
                self._kronos_cached = KronosClassifier()
            return self._kronos_cached

    pipe = _FakePipeline()

    # Flag off → None
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    assert pipe._kronos_or_none is None

    # Flag on → KronosClassifier instance created and cached
    monkeypatch.setenv(_ENV_FLAG, "1")
    instance = pipe._kronos_or_none
    assert isinstance(instance, KronosClassifier)
    # Second access returns same cached instance
    assert pipe._kronos_or_none is instance

    # Flag off again → None and cache cleared
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    assert pipe._kronos_or_none is None


# ---------------------------------------------------------------------------
# Pipeline helper — _call_agent_analyze_kronos
# ---------------------------------------------------------------------------


async def test_pipeline_kronos_disabled_returns_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_KRONOS is unset, _call_agent_analyze_kronos returns neutral dict."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.pipeline import TradingPipeline

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {}
    # Simulate disabled state without a cached instance
    if hasattr(pipeline, "_kronos_cached"):
        del pipeline._kronos_cached

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result == {"signal": 0.0, "confidence": 0.0, "summary": "Kronos disabled"}


async def test_pipeline_kronos_enabled_returns_classify_result(
    monkeypatch: pytest.MonkeyPatch,
    bars_df: pd.DataFrame,
) -> None:
    """When ENABLE_KRONOS=1 and bars are available, classify() result propagates."""
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import KronosClassifier
    from agents.pipeline import TradingPipeline

    fake_data_mgr = MagicMock()
    fake_data_mgr.get_bars = AsyncMock(return_value=bars_df)

    fake_tech = MagicMock()
    fake_tech._data = fake_data_mgr

    kronos = KronosClassifier()
    expected_result = {"signal": 0.0, "confidence": 0.0, "summary": "stub — predictor not wired"}
    kronos.classify = AsyncMock(return_value=expected_result)

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {"technical": fake_tech}
    pipeline._kronos_cached = kronos  # inject cached instance directly

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert result["summary"] == "stub — predictor not wired"
    # verify classify was called with a DataFrame (not a list of dicts) AND symbol
    call_args = kronos.classify.call_args[0]
    call_kwargs = kronos.classify.call_args[1]
    assert isinstance(call_args[0], pd.DataFrame)
    assert call_kwargs.get("symbol") == "MES" or (
        len(call_args) > 1 and call_args[1] == "MES"
    ), f"Expected symbol='MES' passed to classify; call_args={call_args}, call_kwargs={call_kwargs}"


async def test_pipeline_kronos_handles_missing_data_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When technical agent has no _data attribute, returns 'data unavailable' dict."""
    from unittest.mock import MagicMock

    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import KronosClassifier
    from agents.pipeline import TradingPipeline

    fake_tech = MagicMock(spec=[])  # no _data attribute

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {"technical": fake_tech}
    pipeline._kronos_cached = KronosClassifier()  # inject so _kronos_or_none returns it

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result == {"signal": 0.0, "confidence": 0.0, "summary": "data unavailable"}


# ---------------------------------------------------------------------------
# _threshold_for() — per-instrument threshold selection
# ---------------------------------------------------------------------------


def test_threshold_for_known_symbols() -> None:
    """Known symbols return their calibrated thresholds."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    assert clf._threshold_for("MES") == pytest.approx(48.0)
    assert clf._threshold_for("MNQ") == pytest.approx(63.0)
    assert clf._threshold_for("MCL") == pytest.approx(207.0)


def test_threshold_for_unknown_symbol_falls_back() -> None:
    """An unknown symbol falls back to BULL_BEAR_THRESHOLD_BPS_DEFAULT (63 bps)."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    assert clf._threshold_for("XYZ") == pytest.approx(clf.BULL_BEAR_THRESHOLD_BPS_DEFAULT)
    assert clf._threshold_for("XYZ") == pytest.approx(63.0)


def test_threshold_for_none_falls_back() -> None:
    """symbol=None falls back to BULL_BEAR_THRESHOLD_BPS_DEFAULT (63 bps)."""
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    assert clf._threshold_for(None) == pytest.approx(clf.BULL_BEAR_THRESHOLD_BPS_DEFAULT)
    assert clf._threshold_for(None) == pytest.approx(63.0)


def test_classify_with_symbol_uses_specific_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """classify() uses per-instrument threshold — 50 bps triggers MES (48) but not MCL (207).

    We inject a real forecast directly into _forecast_to_verdict to avoid the
    async _predict_async stub path (which always returns None -> neutral).
    """
    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()

    # 50 bps move: above MES threshold (48) → should produce a non-zero signal
    bars = pd.DataFrame({"close": [100.0] * 15})
    forecast_50bps = pd.DataFrame({"close": [100.50] * 5})

    mes_result = clf._forecast_to_verdict(forecast_50bps, bars, symbol="MES")
    assert mes_result["signal"] > 0.0, (
        f"50 bps should exceed MES threshold (48 bps) and produce bull signal; "
        f"got signal={mes_result['signal']}"
    )

    # Same 50 bps move against MCL threshold (207) → should stay neutral
    mcl_result = clf._forecast_to_verdict(forecast_50bps, bars, symbol="MCL")
    assert mcl_result["signal"] == pytest.approx(0.0), (
        f"50 bps is below MCL threshold (207 bps) and should produce neutral signal; "
        f"got signal={mcl_result['signal']}"
    )


# ---------------------------------------------------------------------------
# Real predictor wiring — graceful degradation when package is missing
# ---------------------------------------------------------------------------


def test_predict_sync_returns_none_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Kronos package is absent, _predict_sync returns None (no raise)."""
    import agents.kronos_classifier as kc_mod

    # Force the availability flag off to simulate missing package
    monkeypatch.setattr(kc_mod, "_KRONOS_AVAILABLE", False)
    # Reset singleton so the availability check takes effect
    monkeypatch.setattr(kc_mod, "_PREDICTOR_SINGLETON", None)
    monkeypatch.setattr(kc_mod, "_PREDICTOR_MODEL_PATH", None)

    clf = kc_mod.KronosClassifier()
    bars = pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(20)],
            "high": [101.0 + i * 0.1 for i in range(20)],
            "low": [99.0 + i * 0.1 for i in range(20)],
            "close": [100.5 + i * 0.1 for i in range(20)],
        }
    )
    result = clf._predict_sync(bars)

    assert result is None, f"Expected None when package missing; got {result!r}"


async def test_async_predict_returns_neutral_when_sync_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _predict_sync returns None, classify() returns a neutral dict."""
    from unittest.mock import patch

    import agents.kronos_classifier as kc_mod

    # Force _predict_sync to always return None (simulates missing package)
    monkeypatch.setattr(kc_mod, "_KRONOS_AVAILABLE", False)
    monkeypatch.setattr(kc_mod, "_PREDICTOR_SINGLETON", None)
    monkeypatch.setattr(kc_mod, "_PREDICTOR_MODEL_PATH", None)

    clf = kc_mod.KronosClassifier()
    bars = pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(20)],
            "high": [101.0 + i * 0.1 for i in range(20)],
            "low": [99.0 + i * 0.1 for i in range(20)],
            "close": [100.5 + i * 0.1 for i in range(20)],
        }
    )

    result = await clf.classify(bars)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    # The neutral path for a missing predictor produces the stub summary
    assert isinstance(result["summary"], str) and len(result["summary"]) > 0


def test_classifier_caches_predictor_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_or_load_predictor returns the cached singleton on the second call.

    Tests the real caching function directly: seeds the module-level singleton
    with a fake predictor object, then verifies a second call with the same
    model_path returns the identical object without triggering from_pretrained.
    """
    from unittest.mock import MagicMock

    import agents.kronos_classifier as kc_mod

    fake_predictor = MagicMock(name="fake_predictor")
    model_path = "NeoQuasar/Kronos-mini"
    tokenizer_path = "NeoQuasar/Kronos-Tokenizer-2k"

    # Seed the singleton as if a prior load succeeded
    monkeypatch.setattr(kc_mod, "_KRONOS_AVAILABLE", True)
    monkeypatch.setattr(kc_mod, "_PREDICTOR_SINGLETON", fake_predictor)
    monkeypatch.setattr(kc_mod, "_PREDICTOR_MODEL_PATH", model_path)

    # Patch the class constructors — if from_pretrained is called, the test fails loudly
    bad_cls = MagicMock(name="should-not-be-called")
    bad_cls.from_pretrained.side_effect = AssertionError("from_pretrained unexpectedly called")
    monkeypatch.setattr(kc_mod, "_KronosModelClass", bad_cls)
    monkeypatch.setattr(kc_mod, "_KronosTokenizerClass", bad_cls)
    monkeypatch.setattr(kc_mod, "_KronosPredictorClass", bad_cls)

    # First call: singleton already populated — must return it immediately
    result1 = kc_mod._get_or_load_predictor(model_path, tokenizer_path)
    # Second call with same path: still returns cached instance
    result2 = kc_mod._get_or_load_predictor(model_path, tokenizer_path)

    assert result1 is fake_predictor, "First call must return seeded singleton"
    assert result2 is fake_predictor, "Second call must return cached singleton without reload"
    bad_cls.from_pretrained.assert_not_called()
