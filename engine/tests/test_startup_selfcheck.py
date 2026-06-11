"""I3: post-init startup self-check tests.

Covers run_post_init_selfcheck() invariant semantics and the
log_post_init_selfcheck() WARNING emission contract.
"""

import logging
import types

from startup_checks import log_post_init_selfcheck, run_post_init_selfcheck


class _FakeFlags:
    """Stand-in for the FeatureFlags singleton."""

    def __init__(self, rl_enabled=False, broken=False):
        self._rl = rl_enabled
        self._broken = broken

    def list_flags(self):
        if self._broken:
            raise RuntimeError("flags db unavailable")
        return [{"name": "ENABLE_RL_TRADING", "enabled": self._rl}]

    def is_enabled(self, flag_name):
        if self._broken:
            raise RuntimeError("flags db unavailable")
        return self._rl if flag_name == "ENABLE_RL_TRADING" else False


def _cfg(**overrides):
    base = {
        "LIVE_TRADING_ENABLED": False,
        "REQUIRE_HUMAN_APPROVAL": True,
        "ALLOW_PAPER_SIMULATED_ORDERS": True,
        "ANTHROPIC_API_KEY": "test-key",
        "GOOGLE_API_KEY": "test-key",
        "OPENAI_API_KEY": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _by_name(results, name):
    return next(r for r in results if r.name == name)


def _clear_provider_env(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "JARVIS_LLM_VERTEX_FAILOVER",
    ):
        monkeypatch.delenv(var, raising=False)


class TestRunPostInitSelfcheck:
    def test_all_green(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(_cfg())
        for name in (
            "Flags Table",
            "RL Gate",
            "Fidelity Collector",
            "DO_NOT_TRADE List",
            "Trading Mode",
            "LLM Provider Chain",
        ):
            assert _by_name(results, name).status == "pass", name

    def test_rl_gate_on_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags(rl_enabled=True))
        results = run_post_init_selfcheck(_cfg())
        rl = _by_name(results, "RL Gate")
        assert rl.status == "warn"
        assert "ENABLE_RL_TRADING" in rl.message

    def test_flags_table_unreadable_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags(broken=True))
        results = run_post_init_selfcheck(_cfg())
        assert _by_name(results, "Flags Table").status == "warn"
        assert _by_name(results, "RL Gate").status == "warn"

    def test_flags_singleton_missing_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", None)
        results = run_post_init_selfcheck(_cfg())
        assert _by_name(results, "Flags Table").status == "warn"

    def test_fidelity_reverted_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(_cfg(ALLOW_PAPER_SIMULATED_ORDERS=False))
        fid = _by_name(results, "Fidelity Collector")
        assert fid.status == "warn"
        assert "ALLOW_PAPER_SIMULATED_ORDERS=False" in fid.message

    def test_live_mode_violation_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(
            _cfg(LIVE_TRADING_ENABLED=True, REQUIRE_HUMAN_APPROVAL=False)
        )
        mode = _by_name(results, "Trading Mode")
        assert mode.status == "warn"
        assert "LIVE_TRADING_ENABLED=True" in mode.message
        assert "REQUIRE_HUMAN_APPROVAL=False" in mode.message

    def test_no_provider_keys_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(
            _cfg(ANTHROPIC_API_KEY="", GOOGLE_API_KEY="", OPENAI_API_KEY="")
        )
        chain = _by_name(results, "LLM Provider Chain")
        assert chain.status == "warn"
        assert "NO LLM provider configured" in chain.message

    def test_single_leg_chain_warns(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(
            _cfg(ANTHROPIC_API_KEY="", GOOGLE_API_KEY="only-leg", OPENAI_API_KEY="")
        )
        chain = _by_name(results, "LLM Provider Chain")
        assert chain.status == "warn"
        assert "single-leg" in chain.message

    def test_do_not_trade_listed(self, monkeypatch):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        results = run_post_init_selfcheck(_cfg())
        dnt = _by_name(results, "DO_NOT_TRADE List")
        assert dnt.status == "pass"
        assert "MCL" in dnt.message and "MNQ" in dnt.message


class TestLogPostInitSelfcheck:
    def test_emits_info_block_and_specific_warnings(self, monkeypatch, caplog):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags(rl_enabled=True))
        with caplog.at_level(logging.INFO, logger="startup_checks"):
            log_post_init_selfcheck(_cfg())
        info_blocks = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "STARTUP SELF-CHECK" in r.getMessage()
        ]
        assert len(info_blocks) == 1
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("RL Gate" in w for w in warnings)

    def test_all_green_emits_no_warnings(self, monkeypatch, caplog):
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr("flags.registry._instance", _FakeFlags())
        with caplog.at_level(logging.INFO, logger="startup_checks"):
            log_post_init_selfcheck(_cfg())
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []
