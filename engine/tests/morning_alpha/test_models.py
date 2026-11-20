from datetime import UTC, datetime

import pytest

from morning_alpha.clock import FrozenClock
from morning_alpha.config import MorningAlphaConfig
from morning_alpha.models import StrategyKey, TradePlan


def _plan(**overrides):
    data = dict(
        symbol="XYZ",
        strategy=StrategyKey(strategy_id="rs", version="1.0.0"),
        as_of=datetime(2026, 9, 15, 13, 0, tzinfo=UTC),
        side="long",
        entry=100.0,
        stop=98.0,
        targets=(104.0, 106.0, 108.0),
        risk_per_share=2.0,
        account_equity=3000.0,
        risk_fraction=0.005,
        shares=7,
        max_dollar_risk=14.0,
        expected_r=2.0,
    )
    data.update(overrides)
    return TradePlan(**data)


def test_strategy_key_is_versioned():
    key = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
    assert key.canonical == "relative_strength_breakout@1.0.0"


def test_trade_plan_rejects_less_than_two_r():
    with pytest.raises(ValueError, match="minimum 2.0R"):
        _plan(expected_r=1.5)


def test_trade_plan_rejects_more_than_one_percent_risk():
    with pytest.raises(ValueError, match="<= 0.01"):
        _plan(risk_fraction=0.0101)


def test_trade_plan_rejects_long_stop_above_entry():
    with pytest.raises(ValueError, match="long stop must be below entry"):
        _plan(stop=100.5)


def test_frozen_clock_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 9, 15, 13, 0))


def test_frozen_clock_returns_exact_timestamp():
    ts = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
    assert FrozenClock(ts).now() == ts


def test_config_defaults_match_approved_small_account_policy():
    cfg = MorningAlphaConfig()
    assert cfg.enabled is False
    assert cfg.paper_observation is False
    assert cfg.account_equity == 3000.0
    assert cfg.default_risk_fraction == 0.005
    assert cfg.max_risk_fraction == 0.01
    assert cfg.min_expected_r == 2.0
    assert cfg.max_initial_portfolio_heat == 0.0125
    assert cfg.max_theme_heat == 0.01


def test_config_from_env_requires_explicit_enablement(monkeypatch):
    monkeypatch.setenv("MORNING_ALPHA_ENABLED", "true")
    monkeypatch.setenv("MORNING_ALPHA_PAPER_OBSERVATION", "true")
    cfg = MorningAlphaConfig.from_env()
    assert cfg.enabled is True
    assert cfg.paper_observation is True


def test_paper_observation_cannot_be_enabled_while_system_disabled():
    with pytest.raises(ValueError, match="paper_observation requires enabled=true"):
        MorningAlphaConfig(enabled=False, paper_observation=True)


def test_config_from_env_rejects_ambiguous_boolean(monkeypatch):
    monkeypatch.setenv("MORNING_ALPHA_ENABLED", "maybe")
    with pytest.raises(ValueError, match="MORNING_ALPHA_ENABLED"):
        MorningAlphaConfig.from_env()
