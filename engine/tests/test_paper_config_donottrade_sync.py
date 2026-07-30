"""
Defense-in-depth regression tests: paper config / DO_NOT_TRADE_SYMBOLS sync.

Root cause of the MNQ wiring leak (commit 0772e20, 2026-05-06/07):
    paper_config.py had MNQ_PAPER_CONFIG with enabled=True.
    The market_open_scan_job dispatcher called analyze_and_decide for MNQ
    WITHOUT cross-checking DO_NOT_TRADE_SYMBOLS, resulting in 55 erroneous
    trades on a blocklisted symbol.

Remediation (2026-05-07):
    1. Config layer: MCL/MNQ now have enabled=False (primary control).
    2. Dispatcher layer: market_open_scan_job and intraday_scan_15m_job now
       cross-check DO_NOT_TRADE_SYMBOLS before dispatching signals, emitting
       a WARNING and skipping any enabled=True config for a blocked symbol.
    3. Startup check: _check_paper_config_do_not_trade_sync() added to
       startup_checks.py — engine refuses to boot with a FAIL verdict if any
       enabled config targets a DO_NOT_TRADE symbol.

These tests prevent future drift where a config gets re-enabled for a symbol
that's still blocked at the verdict layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test 1: no paper config currently has enabled=True for a DO_NOT_TRADE symbol
# ---------------------------------------------------------------------------

class TestNoEnabledConfigForDoNotTradeSymbol:
    """
    Deterministic regression: iterate all paper configs and assert that every
    config with enabled=True has a symbol NOT in DO_NOT_TRADE_SYMBOLS.

    If this test fails, a config got re-enabled for a blocked symbol —
    exactly the wiring-leak class that caused 55 MNQ phantom trades.
    """

    def test_no_paper_config_enabled_for_donottrade_symbol(self):
        """No PAPER_CONFIGS entry should have enabled=True if symbol is blocked."""
        from backtest.paper_config import PAPER_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS

        violations = []
        for sym, cfg in PAPER_CONFIGS.items():
            if cfg.get("enabled", False) and sym in DO_NOT_TRADE_SYMBOLS:
                violations.append(
                    f"{sym} ({cfg.get('interval','?')}): "
                    f"enabled=True but in DO_NOT_TRADE_SYMBOLS"
                )

        assert violations == [], (
            "Paper config / DO_NOT_TRADE drift detected — "
            "the following configs are enabled for blocked symbols:\n  "
            + "\n  ".join(violations)
            + "\nFix: set enabled=False in engine/backtest/paper_config.py "
            "or remove the symbol from DO_NOT_TRADE_SYMBOLS in signals.py."
        )

    def test_no_fifteen_min_config_enabled_for_donottrade_symbol(self):
        """No FIFTEEN_MIN_CONFIGS entry should have enabled=True if symbol is blocked."""
        from backtest.paper_config import FIFTEEN_MIN_CONFIGS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS

        violations = []
        for sym, cfg in FIFTEEN_MIN_CONFIGS.items():
            if cfg.get("enabled", False) and sym in DO_NOT_TRADE_SYMBOLS:
                violations.append(
                    f"{sym} ({cfg.get('interval','?')} 15m): "
                    f"enabled=True but in DO_NOT_TRADE_SYMBOLS"
                )

        assert violations == [], (
            "15m paper config / DO_NOT_TRADE drift detected:\n  "
            + "\n  ".join(violations)
        )

    def test_active_instruments_list_contains_no_donottrade_symbols(self):
        """ACTIVE_INSTRUMENTS (derived from PAPER_CONFIGS) must not include blocked symbols."""
        from backtest.paper_config import ACTIVE_INSTRUMENTS
        from backtest.signals import DO_NOT_TRADE_SYMBOLS

        blocked_active = [s for s in ACTIVE_INSTRUMENTS if s in DO_NOT_TRADE_SYMBOLS]
        assert blocked_active == [], (
            f"ACTIVE_INSTRUMENTS contains DO_NOT_TRADE symbols: {blocked_active}. "
            "ACTIVE_INSTRUMENTS is derived from PAPER_CONFIGS via a list comprehension "
            "that filters by enabled=True — if symbols appear here they're misconfigured."
        )

    def test_currently_enabled_symbols_have_gate_v2_pass_verdicts(self):
        """
        Each enabled=True config should correspond to a symbol that passed gate v2.
        (Soft check — warns but doesn't fail if verdict files are missing.)

        This is intentionally a sanity check, not a hard gate, because the
        engine can run in degraded mode without verdict files on disk.
        """
        import os

        from backtest.paper_config import PAPER_CONFIGS

        VERDICTS_DIR = os.path.join(
            os.path.dirname(__file__), "..", "data", "gate_v2_verdicts"
        )

        enabled_symbols = [sym for sym, cfg in PAPER_CONFIGS.items() if cfg.get("enabled")]

        if not os.path.isdir(VERDICTS_DIR):
            pytest.skip("gate_v2_verdicts/ not on disk — skipping verdict-file check")

        # Verdict JSONs are untracked engine runtime state (commit e484574), so
        # CI checks out the directory (archive/ stays tracked) with no verdict
        # files in it. Only enforce the per-symbol check where runtime verdicts
        # actually exist — this stays a drift detector on dev machines.
        all_verdicts = [f for f in os.listdir(VERDICTS_DIR) if f.endswith(".json")]
        if not all_verdicts:
            pytest.skip(
                "gate_v2_verdicts/ has no verdict JSONs (untracked runtime "
                "state, e.g. CI checkout) — skipping verdict-file check"
            )

        for sym in enabled_symbols:
            # Look for any JSON verdict file starting with the symbol name
            matching = [
                f for f in os.listdir(VERDICTS_DIR)
                if f.startswith(sym) and f.endswith(".json")
            ]
            assert matching, (
                f"{sym} is enabled=True but has no gate_v2 verdict file in "
                f"{VERDICTS_DIR}. Authorized paper trading requires a PASS verdict."
            )


# ---------------------------------------------------------------------------
# Test 2: startup check catches a misconfigured enabled=True for a blocked symbol
# ---------------------------------------------------------------------------

class TestStartupCheckDoNotTradeSyncFunction:
    """
    The _check_paper_config_do_not_trade_sync() function added to startup_checks.py
    should FAIL when any config has enabled=True for a DO_NOT_TRADE symbol, and
    PASS when everything is consistent.
    """

    def test_startup_check_passes_with_consistent_config(self):
        """Startup check passes when no enabled config targets a blocked symbol."""
        from startup_checks import _check_paper_config_do_not_trade_sync

        # Current state should be consistent — all DO_NOT_TRADE symbols are disabled
        result = _check_paper_config_do_not_trade_sync()
        assert result.status == "pass", (
            f"Startup check failed unexpectedly: {result.message}"
        )

    def test_startup_check_fails_when_enabled_config_for_blocked_symbol(self):
        """Startup check returns FAIL when a blocked symbol has enabled=True."""
        from startup_checks import _check_paper_config_do_not_trade_sync

        fake_paper_configs = {
            "MNQ": {"symbol": "MNQ", "interval": "1h", "enabled": True},
            "MES": {"symbol": "MES", "interval": "1h", "enabled": True},
        }
        fake_15m_configs = {}
        fake_do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        with patch("startup_checks.PAPER_CONFIGS", fake_paper_configs, create=True), \
             patch("startup_checks.FIFTEEN_MIN_CONFIGS", fake_15m_configs, create=True), \
             patch("startup_checks.DO_NOT_TRADE_SYMBOLS", fake_do_not_trade, create=True):
            # Patch the imports inside the function
            with patch.dict("sys.modules", {}):
                import sys
                mock_paper_config = MagicMock()
                mock_paper_config.PAPER_CONFIGS = fake_paper_configs
                mock_paper_config.FIFTEEN_MIN_CONFIGS = fake_15m_configs
                mock_signals = MagicMock()
                mock_signals.DO_NOT_TRADE_SYMBOLS = fake_do_not_trade

                orig_paper = sys.modules.get("backtest.paper_config")
                orig_signals = sys.modules.get("backtest.signals")
                try:
                    sys.modules["backtest.paper_config"] = mock_paper_config
                    sys.modules["backtest.signals"] = mock_signals
                    result = _check_paper_config_do_not_trade_sync()
                finally:
                    if orig_paper is not None:
                        sys.modules["backtest.paper_config"] = orig_paper
                    elif "backtest.paper_config" in sys.modules:
                        del sys.modules["backtest.paper_config"]
                    if orig_signals is not None:
                        sys.modules["backtest.signals"] = orig_signals
                    elif "backtest.signals" in sys.modules:
                        del sys.modules["backtest.signals"]

        assert result.status == "fail", (
            f"Expected FAIL when MNQ enabled=True + in DO_NOT_TRADE, got: {result.status}"
        )
        assert "MNQ" in result.message, (
            f"Expected MNQ in failure message, got: {result.message}"
        )

    def test_startup_check_passes_when_blocked_symbol_is_disabled(self):
        """Startup check passes when blocked symbol has enabled=False."""
        from startup_checks import _check_paper_config_do_not_trade_sync

        fake_paper_configs = {
            # MNQ disabled — no violation
            "MNQ": {"symbol": "MNQ", "interval": "1h", "enabled": False},
            # MES enabled but NOT in DO_NOT_TRADE — allowed
            "MES": {"symbol": "MES", "interval": "1h", "enabled": True},
        }
        fake_15m_configs = {}
        fake_do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        import sys
        mock_paper_config = MagicMock()
        mock_paper_config.PAPER_CONFIGS = fake_paper_configs
        mock_paper_config.FIFTEEN_MIN_CONFIGS = fake_15m_configs
        mock_signals = MagicMock()
        mock_signals.DO_NOT_TRADE_SYMBOLS = fake_do_not_trade

        orig_paper = sys.modules.get("backtest.paper_config")
        orig_signals = sys.modules.get("backtest.signals")
        try:
            sys.modules["backtest.paper_config"] = mock_paper_config
            sys.modules["backtest.signals"] = mock_signals
            result = _check_paper_config_do_not_trade_sync()
        finally:
            if orig_paper is not None:
                sys.modules["backtest.paper_config"] = orig_paper
            elif "backtest.paper_config" in sys.modules:
                del sys.modules["backtest.paper_config"]
            if orig_signals is not None:
                sys.modules["backtest.signals"] = orig_signals
            elif "backtest.signals" in sys.modules:
                del sys.modules["backtest.signals"]

        assert result.status == "pass", (
            f"Expected PASS when blocked symbols are disabled, got: {result.status} — {result.message}"
        )

    def test_startup_check_is_registered_in_run_startup_checks(self):
        """
        _check_paper_config_do_not_trade_sync must be called by run_startup_checks.
        Verified by running with a patched version and checking the result names.
        """
        from startup_checks import run_startup_checks

        fake_config = SimpleNamespace(
            API_KEY="test-key-abc",
            IBKR_PORT=4002,
            LIVE_TRADING_ENABLED=False,
            REQUIRE_HUMAN_APPROVAL=True,
            SQLITE_DB_PATH=":memory:",
            POLYGON_API_KEY=None,
            FRED_API_KEY=None,
        )

        results = run_startup_checks(fake_config)
        result_names = [r.name for r in results]
        assert "Paper Config / DO_NOT_TRADE Sync" in result_names, (
            "run_startup_checks does not call _check_paper_config_do_not_trade_sync. "
            "Add it to the results list in startup_checks.py."
        )


# ---------------------------------------------------------------------------
# Test 3: dispatcher rejects enabled=True for DO_NOT_TRADE (unit test via
#         startup check's internal logic, which mirrors the dispatcher guard)
# ---------------------------------------------------------------------------

class TestDispatcherCrossCheckLogic:
    """
    The cross-check logic in market_open_scan_job mirrors what the startup check
    does: skip any symbol that is both enabled=True in PAPER_CONFIGS and in
    DO_NOT_TRADE_SYMBOLS.

    These tests verify the logic in isolation by simulating the filter.
    """

    def _run_dispatcher_filter(
        self,
        paper_configs: dict,
        do_not_trade: frozenset,
    ) -> tuple[list[str], list[str]]:
        """
        Simulate the dispatcher filter logic from market_open_scan_job (2026-05-07 version):
            - accepted: symbols where enabled=True AND symbol NOT in DO_NOT_TRADE
            - rejected: symbols where enabled=True AND symbol IN DO_NOT_TRADE
        """
        accepted = []
        rejected = []
        for sym, cfg in paper_configs.items():
            if not cfg.get("enabled", False):
                continue
            if sym in do_not_trade:
                rejected.append(sym)
            else:
                accepted.append(sym)
        return accepted, rejected

    def test_dispatcher_rejects_enabled_donottrade_symbol(self):
        """Mock config with enabled=True for a DO_NOT_TRADE symbol — dispatcher rejects it."""
        paper_configs = {
            "MNQ": {"symbol": "MNQ", "interval": "1h", "enabled": True},
        }
        do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        accepted, rejected = self._run_dispatcher_filter(paper_configs, do_not_trade)

        assert "MNQ" not in accepted, "MNQ should be rejected — it's in DO_NOT_TRADE"
        assert "MNQ" in rejected, "MNQ should appear in the rejected list"

    def test_dispatcher_accepts_enabled_clean_symbol(self):
        """Mock config with enabled=True for a clean symbol — dispatcher accepts it."""
        paper_configs = {
            "MES": {"symbol": "MES", "interval": "1h", "enabled": True},
        }
        do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        accepted, rejected = self._run_dispatcher_filter(paper_configs, do_not_trade)

        assert "MES" in accepted, "MES should be accepted — it's not in DO_NOT_TRADE"
        assert "MES" not in rejected, "MES should not be rejected"

    def test_dispatcher_skips_disabled_clean_symbol(self):
        """Disabled symbol is not dispatched regardless of DO_NOT_TRADE membership."""
        paper_configs = {
            "MES": {"symbol": "MES", "interval": "1h", "enabled": False},
        }
        do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        accepted, rejected = self._run_dispatcher_filter(paper_configs, do_not_trade)

        assert "MES" not in accepted
        assert "MES" not in rejected

    def test_dispatcher_mixed_configs(self):
        """
        Mixed bag: one clean enabled, one DO_NOT_TRADE enabled, one disabled.
        Only the clean enabled should be accepted.
        """
        paper_configs = {
            "MES": {"symbol": "MES", "interval": "1h", "enabled": True},
            "MGC": {"symbol": "MGC", "interval": "1h", "enabled": True},
            "MNQ": {"symbol": "MNQ", "interval": "1h", "enabled": True},   # should be blocked
            "MCL": {"symbol": "MCL", "interval": "1h", "enabled": False},  # disabled
        }
        do_not_trade = frozenset({"MCL", "MNQ", "M2K"})

        accepted, rejected = self._run_dispatcher_filter(paper_configs, do_not_trade)

        assert set(accepted) == {"MES", "MGC"}, f"Unexpected accepted: {accepted}"
        assert set(rejected) == {"MNQ"}, f"Unexpected rejected: {rejected}"

    def test_dispatcher_empty_configs_returns_empty(self):
        """Empty PAPER_CONFIGS → empty accepted and rejected lists."""
        accepted, rejected = self._run_dispatcher_filter({}, frozenset({"MCL", "MNQ"}))
        assert accepted == []
        assert rejected == []


# ---------------------------------------------------------------------------
# Test 4: DO_NOT_TRADE_SYMBOLS is a frozenset of known blocked symbols
# ---------------------------------------------------------------------------

class TestDoNotTradeSymbolsConstant:
    """
    The DO_NOT_TRADE_SYMBOLS frozenset must contain exactly the expected symbols
    and must not accidentally include symbols with validated edges (MES, MGC).
    """

    def test_donottrade_symbols_is_frozenset(self):
        """DO_NOT_TRADE_SYMBOLS is a frozenset, not a mutable set."""
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
        assert isinstance(DO_NOT_TRADE_SYMBOLS, frozenset)

    def test_donottrade_symbols_contains_expected_blocked(self):
        """MCL, MNQ, M2K are all in DO_NOT_TRADE_SYMBOLS per 2026-05-06 exhaustion."""
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
        assert "MCL" in DO_NOT_TRADE_SYMBOLS
        assert "MNQ" in DO_NOT_TRADE_SYMBOLS
        assert "M2K" in DO_NOT_TRADE_SYMBOLS

    def test_donottrade_symbols_blocks_mgc_not_mes(self):
        """MGC is blocked as of 2026-07-29 (honest-data-drain DSR correction).

        MES is deliberately NOT blocked -- it remains Amo's most-traded vehicle
        and must never be added to DO_NOT_TRADE_SYMBOLS without his explicit
        direction, regardless of what any analysis (including honest-data-drain)
        concludes about it.
        """
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
        assert "MES" not in DO_NOT_TRADE_SYMBOLS, (
            "MES must never be in DO_NOT_TRADE_SYMBOLS -- it is Amo's most-traded vehicle."
        )
        assert "MGC" in DO_NOT_TRADE_SYMBOLS, (
            "MGC's gate v2 PASS did not survive DSR correction at the true trial "
            "count (honest-data-drain, 2026-07-27) — it should be in DO_NOT_TRADE_SYMBOLS."
        )


# ---------------------------------------------------------------------------
# Test 5: CapitalAllocator shares the single DO_NOT_TRADE authority
# ---------------------------------------------------------------------------

class TestCapitalAllocatorUsesSingleAuthority:
    """
    CapitalAllocator.rebalance() previously hardcoded its own private
    _DO_NOT_TRADE = {"MCL", "MNQ", "MGC"} frozenset. That disagreed with the
    single authority backtest.signals.DO_NOT_TRADE_SYMBOLS = {"MCL","MNQ","M2K"}
    in *both* directions — it wrongly blocked MGC (gate-v2 PASS, tradeable) and
    wrongly allowed M2K (blocked). The rebalance() output is logged-only today
    (eod_scheduler.py), so the divergence was inert — but it is exactly the
    third-config split-brain that the MNQ wiring leak taught us to forbid.

    These tests pin the allocator to the shared authority so the split-brain
    can never silently return: if anyone re-introduces a divergent private list,
    test_rebalance_zeroes_exactly_the_donottrade_authority fails.
    """

    def test_rebalance_zeroes_exactly_the_donottrade_authority(self):
        """rebalance() must zero precisely the symbols in DO_NOT_TRADE_SYMBOLS."""
        from backtest.signals import DO_NOT_TRADE_SYMBOLS
        from orchestrator.capital_allocator import CapitalAllocator

        # Mix of every blocked symbol plus two tradeable ones, all with strong
        # Sharpe so only the blocklist (not the perf rules) can zero them.
        symbols = sorted(set(DO_NOT_TRADE_SYMBOLS) | {"MES", "MGC"})
        perf = {s: {"sharpe": 2.0, "current_allocation": 0.25} for s in symbols}

        allocator = CapitalAllocator(dict.fromkeys(symbols, 10_000.0))
        new_alloc = allocator.rebalance(perf)

        zeroed = {s for s, v in new_alloc.items() if v == 0.0}
        assert zeroed == set(DO_NOT_TRADE_SYMBOLS), (
            f"Allocator zeroed {zeroed} but the single authority "
            f"DO_NOT_TRADE_SYMBOLS is {set(DO_NOT_TRADE_SYMBOLS)}. The allocator "
            "must import the authority from backtest.signals, not keep a private list."
        )

    def test_rebalance_blocks_m2k_and_mgc(self):
        """Pins the symbols the old private list got wrong (M2K) plus the
        2026-07-29 honest-data-drain addition (MGC). MES stays tradeable --
        it is Amo's most-traded vehicle and must never be blocked without his
        explicit direction. See test_donottrade_symbols_blocks_mgc_not_mes above.
        """
        from orchestrator.capital_allocator import CapitalAllocator

        perf = {
            "M2K": {"sharpe": 2.0, "current_allocation": 0.25},  # blocked authority
            "MGC": {"sharpe": 2.0, "current_allocation": 0.25},  # blocked (honest-data-drain)
            "MES": {"sharpe": 2.0, "current_allocation": 0.25},  # tradeable (gate-v2 PASS)
        }
        allocator = CapitalAllocator(
            {"M2K": 10_000.0, "MGC": 50_000.0, "MES": 50_000.0}
        )
        new_alloc = allocator.rebalance(perf)

        assert new_alloc.get("M2K", 1.0) == 0.0, (
            "M2K is in DO_NOT_TRADE_SYMBOLS and must be zeroed by rebalance()."
        )
        assert new_alloc.get("MGC", 1.0) == 0.0, (
            "MGC is in DO_NOT_TRADE_SYMBOLS (honest-data-drain, 2026-07-29) and must be zeroed."
        )
        assert new_alloc.get("MES", 0.0) > 0.0, (
            "MES is tradeable (gate-v2 PASS) and must receive a non-zero allocation."
        )
