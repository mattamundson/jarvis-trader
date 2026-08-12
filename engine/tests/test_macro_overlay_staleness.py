"""Macro-overlay staleness consumption guard.

Covers ``_macro_bias_allowed`` — the tighter live-consumption cutoff layered on top of
macro_regime's own >10-day UNKNOWN fail-safe. A stale-but-computable RISK_ON must not
be injected as advisory bias once the SPY bar is older than MACRO_BIAS_MAX_STALE_DAYS.
"""

from agents.pipeline import MACRO_BIAS_MAX_STALE_DAYS, _macro_bias_allowed

_BIAS = "MACRO TREND: RISK_ON (weekly SPX uptrend + monthly momentum) — favor longs, normal size."


def _mr(stale, bias=_BIAS):
    return {"bias_line": bias, "stale_days": stale, "state": "RISK_ON"}


def test_fresh_bias_is_injected():
    assert _macro_bias_allowed(_mr(0)) is True
    assert _macro_bias_allowed(_mr(MACRO_BIAS_MAX_STALE_DAYS)) is True  # boundary inclusive


def test_stale_bias_is_suppressed():
    assert _macro_bias_allowed(_mr(MACRO_BIAS_MAX_STALE_DAYS + 1)) is False
    assert _macro_bias_allowed(_mr(99)) is False


def test_empty_bias_is_never_injected():
    # NEUTRAL / UNKNOWN yield an empty bias_line regardless of freshness.
    assert _macro_bias_allowed({"bias_line": "", "stale_days": 0}) is False
    assert _macro_bias_allowed({"bias_line": None, "stale_days": 0}) is False


def test_missing_stale_days_fails_open():
    # macro_regime fail-safes to empty bias_line when data is absent, so a bias_line with
    # no stale_days means the field simply wasn't surfaced — inject rather than false-suppress.
    assert _macro_bias_allowed({"bias_line": _BIAS}) is True
