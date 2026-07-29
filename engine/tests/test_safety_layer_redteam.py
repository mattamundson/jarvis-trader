"""
JARVIS TRADER — Safety Layer Red-Team Test Suite
====================================================
SOTA plan item P3.3 (docs/JARVIS_SOTA_PLAN.md).

Each test class below crafts an ADVERSARIAL attempt to route around one hard
rail in engine/risk/safety_layer.py, then asserts the rail actually held.
This is deliberately distinct from engine/tests/test_safety_layer.py's
happy-path coverage: every test here tries a specific evasion vector
(boundary slip, value-field manipulation, symbol rotation, minimal-order
timing, cross-asset-class disguise) that a bad actor — or a buggy calling
agent — might use to slip an order past a limit.

Test-only: no changes to safety_layer.py, loss_tracker.py, or config.py.
All hard limits are exercised via the public SafetyLayer/OrderRequest API
exactly as the existing safety suite does.

Note on "max margin utilization (40%)": `settings.MAX_MARGIN_UTILIZATION` is
read by routers/phase3_readiness_router.py as a static config-value gate and
surfaced to the LLM prompt in agents/fund_manager.py, but SafetyLayer itself
does not enforce it as a live per-order check. The actual per-order margin
rail enforced by SafetyLayer.check_order() for futures is
`_check_order_value_limits()`'s futures branch, gated by
`MAX_FUTURES_MARGIN_PCT` against the `_FUTURES_MARGIN_BY_ROOT` table — that
is the mechanism this suite's margin-utilization tests exercise, since it is
the rail that actually runs on every order.
"""

from pathlib import Path

import pytest

from risk.loss_tracker import ConsecutiveLossTracker
from risk.safety_layer import KillSwitchReason, OrderRequest, SafetyLayer


def _armed_settings(mock_settings):
    """Bypass the LIVE_TRADING_ENABLED / REQUIRE_HUMAN_APPROVAL gates so the
    hard-limit checks under test are actually reached. Mirrors the pattern
    already established in test_safety_layer.py and test_loss_tracker.py —
    this mutates a per-test mock TradingConfig instance only, never the real
    engine config.
    """
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    return mock_settings


# ---------------------------------------------------------------------------
# Rail 1 — the -2% daily-loss kill switch
# ---------------------------------------------------------------------------


class TestDailyLossKillSwitchRedTeam:
    """Adversarial attempts against the -2% daily realized/total P&L limit."""

    def test_boundary_exact_threshold_not_exploitable_either_direction(
        self, mock_settings
    ):
        """Attacker probes the exact boundary hoping for an off-by-one gap.

        Loss precisely AT the -2% line must pass (strict '<' comparison);
        one cent past it must trip the kill switch. If the comparison were
        ever loosened to '<=' or flipped, one of these two assertions fails.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_DAILY_LOSS_PCT = 0.02
        settings.MAX_DAILY_LOSS_USD = 1_000_000.0  # neutralize the abs-USD gate
        equity = 100_000.0
        rel_limit = -(equity * settings.MAX_DAILY_LOSS_PCT)  # -2000.0

        safety = SafetyLayer(settings)
        safety._daily_realized_pnl = rel_limit  # exactly -2000.0
        order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=500.0
        )
        result = safety.check_order(order, equity)
        assert result.approved is True
        assert safety.is_killed is False

        safety2 = SafetyLayer(settings)
        safety2._daily_realized_pnl = rel_limit - 0.01  # one cent past the line
        result2 = safety2.check_order(order, equity)
        assert result2.approved is False
        assert safety2.is_killed is True
        assert safety2._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_minimal_value_order_does_not_evade_post_breach_halt(self, mock_settings):
        """Attacker tries a $1 order hoping a 'tiny' order slips under the halt.

        The kill-switch check runs before any order-size evaluation, so a
        breach must block orders of ANY size — not just large ones.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_DAILY_LOSS_PCT = 0.02
        settings.MAX_DAILY_LOSS_USD = 1_000_000.0
        equity = 100_000.0
        safety = SafetyLayer(settings)
        safety._daily_realized_pnl = -(equity * 0.02) - 1.0  # just past breach

        tiny_order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=1.0
        )
        result = safety.check_order(tiny_order, equity)
        assert result.approved is False
        assert "kill switch" in (result.rejection_reason or "").lower()

    def test_kill_switch_stays_latched_across_repeated_attempts(self, mock_settings):
        """Attacker hammers the API with repeated resubmissions after breach,
        hoping a race or reset lets one slip through. Every attempt in the
        same window must stay blocked without re-arming.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_DAILY_LOSS_PCT = 0.02
        settings.MAX_DAILY_LOSS_USD = 1_000_000.0
        equity = 100_000.0
        safety = SafetyLayer(settings)
        safety._daily_realized_pnl = -(equity * 0.02) - 500.0

        order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=100.0
        )
        for _ in range(25):
            result = safety.check_order(order, equity)
            assert result.approved is False
            assert safety.is_killed is True


# ---------------------------------------------------------------------------
# Rail 2 — the drawdown halt (-10% code default / -20% paper-phase override)
# ---------------------------------------------------------------------------


class TestDrawdownHaltRedTeam:
    """Adversarial attempts against the peak-equity drawdown halt."""

    def test_boundary_exact_threshold_not_exploitable_either_direction(
        self, mock_settings
    ):
        settings = _armed_settings(mock_settings)
        settings.MAX_DRAWDOWN_PCT = 0.10
        peak = 100_000.0

        safety = SafetyLayer(settings)
        safety._equity_peak = peak
        at_limit_equity = peak * (1 - 0.10)  # exactly 10% down
        order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=500.0
        )
        result = safety.check_order(order, at_limit_equity)
        assert result.approved is True
        assert safety.is_killed is False

        safety2 = SafetyLayer(settings)
        safety2._equity_peak = peak
        past_limit_equity = at_limit_equity - 1.0
        result2 = safety2.check_order(order, past_limit_equity)
        assert result2.approved is False
        assert safety2.is_killed is True
        assert safety2._kill_switch_reason == KillSwitchReason.MAX_DRAWDOWN

    def test_paper_phase_override_widens_but_still_holds(self, mock_settings):
        """The runtime .env override raises the drawdown limit from the
        -10% code default to -20% during the paper phase. A drawdown that
        would have breached the code default (15%) must be ALLOWED under
        the wider override, but the override itself must still be a hard
        line — 20.01% down must still halt.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_DRAWDOWN_PCT = 0.20  # simulated paper-phase override
        peak = 100_000.0
        order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=500.0
        )

        safety = SafetyLayer(settings)
        safety._equity_peak = peak
        fifteen_pct_down = peak * 0.85
        result = safety.check_order(order, fifteen_pct_down)
        assert result.approved is True  # would have breached the -10% default

        safety2 = SafetyLayer(settings)
        safety2._equity_peak = peak
        past_override = peak * 0.80 - 1.0  # just past -20%
        result2 = safety2.check_order(order, past_override)
        assert result2.approved is False
        assert safety2._kill_switch_reason == KillSwitchReason.MAX_DRAWDOWN

    def test_minimal_value_order_does_not_evade_post_breach_halt(self, mock_settings):
        settings = _armed_settings(mock_settings)
        settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(settings)
        safety._equity_peak = 100_000.0
        breached_equity = 85_000.0  # 15% down, past the 10% line

        tiny_order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=1.0
        )
        result = safety.check_order(tiny_order, breached_equity)
        assert result.approved is False
        assert safety.is_killed is True


# ---------------------------------------------------------------------------
# Rail 3 — max position size (5% of portfolio) and max contracts (2 micro)
# ---------------------------------------------------------------------------


class TestPositionSizeAndContractLimitRedTeam:
    def test_position_size_boundary_not_exploitable(self, mock_settings):
        """Order at exactly 5% of portfolio must pass; one cent over must not."""
        settings = _armed_settings(mock_settings)
        settings.MAX_POSITION_SIZE_PCT = 0.05
        settings.MAX_SINGLE_ORDER_VALUE = 10_000.0  # keep the value cap out of the way
        equity = 100_000.0
        max_value = equity * 0.05  # $5,000

        safety = SafetyLayer(settings)
        at_limit = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=max_value
        )
        result = safety.check_order(at_limit, equity)
        assert result.approved is True

        safety2 = SafetyLayer(settings)
        over_limit = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=max_value + 0.01,
        )
        result2 = safety2.check_order(over_limit, equity)
        assert result2.approved is False
        assert "position size" in (result2.rejection_reason or "").lower()

    def test_contract_cap_survives_estimated_value_manipulation(self, mock_settings):
        """Attacker sets a near-zero estimated_value on a futures order hoping
        the contract-count cap is gated on notional value rather than raw
        quantity. It is gated on raw quantity — this must still be rejected
        even though the order 'looks' tiny in dollar terms.

        Uses M2K (not in the overnight-symbol set) so the test is wall-clock
        independent, unlike MES which has a separate post-15:00-CT overnight
        cap that would otherwise confound this specific assertion.

        PRB-22 (2026-07-29): was MGC until SafetyLayer._check_paper_config_enabled
        was added to check_order() — MGC now carries paper_config.enabled=False
        (backtest/paper_config.py) and would be rejected before ever reaching
        the contract-cap check this test exists to exercise. M2K has no
        PAPER_CONFIGS entry at all (only symbols with an explicit enabled=False
        entry are blocked, never the absence of one) and is also outside
        _OVERNIGHT_SYMBOLS, preserving the original test intent.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        settings.MAX_FUTURES_MARGIN_PCT = 0.30
        safety = SafetyLayer(settings)

        order = OrderRequest(
            symbol="M2K",
            quantity=3,  # exceeds the 2-contract cap
            order_type="market",
            is_futures=True,
            estimated_value=0.01,  # attacker disguises the order as trivial
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "contracts exceeds max" in (result.rejection_reason or "").lower()

    def test_contract_cap_boundary_not_exploitable(self, mock_settings):
        """PRB-22 (2026-07-29): symbol swapped MGC -> M2K; see docstring on
        test_contract_cap_survives_estimated_value_manipulation above for why.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        settings.MAX_FUTURES_MARGIN_PCT = 0.30
        safety = SafetyLayer(settings)

        at_limit = OrderRequest(
            symbol="M2K",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=1800.0,
        )
        result = safety.check_order(at_limit, 100_000.0)
        assert result.approved is True

        safety2 = SafetyLayer(settings)
        over_limit = OrderRequest(
            symbol="M2K",
            quantity=3,
            order_type="market",
            is_futures=True,
            estimated_value=2700.0,
        )
        result2 = safety2.check_order(over_limit, 100_000.0)
        assert result2.approved is False


# ---------------------------------------------------------------------------
# Rail 4 — max single order value ($5,000)
# ---------------------------------------------------------------------------


class TestMaxOrderValueRedTeam:
    def test_boundary_not_exploitable(self, mock_settings):
        settings = _armed_settings(mock_settings)
        settings.MAX_SINGLE_ORDER_VALUE = 5_000.0
        settings.MAX_POSITION_SIZE_PCT = 1.0  # keep the pct cap out of the way
        equity = 10_000_000.0

        safety = SafetyLayer(settings)
        at_limit = OrderRequest(
            symbol="SPY", quantity=1, order_type="market", estimated_value=5_000.0
        )
        result = safety.check_order(at_limit, equity)
        assert result.approved is True

        safety2 = SafetyLayer(settings)
        over_limit = OrderRequest(
            symbol="SPY", quantity=1, order_type="market", estimated_value=5_000.01
        )
        result2 = safety2.check_order(over_limit, equity)
        assert result2.approved is False
        assert "exceeds max" in (result2.rejection_reason or "").lower()

    def test_is_futures_flag_cannot_disguise_an_oversized_unknown_root_order(
        self, mock_settings
    ):
        """Attacker sets is_futures=True on an unrecognized root, hoping to
        route into the margin-based branch and skip the notional value cap
        entirely. Unknown roots fall back to the same notional check that
        governs equities, so this must still be rejected.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_SINGLE_ORDER_VALUE = 5_000.0
        safety = SafetyLayer(settings)

        order = OrderRequest(
            symbol="ZZZZ",  # not present in _FUTURES_MARGIN_BY_ROOT
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=50_000.0,
        )
        result = safety.check_order(order, 1_000_000.0)
        assert result.approved is False
        assert "exceeds max" in (result.rejection_reason or "").lower()


# ---------------------------------------------------------------------------
# Rail 5 — max margin utilization (futures margin gate, the live per-order
# enforcement of the "never exceed 40% of available margin" intent — see
# module docstring for why MAX_FUTURES_MARGIN_PCT is the mechanism under
# test rather than the MAX_MARGIN_UTILIZATION config value directly).
# ---------------------------------------------------------------------------


class TestFuturesMarginUtilizationRedTeam:
    def test_boundary_not_exploitable(self, mock_settings):
        settings = _armed_settings(mock_settings)
        settings.MAX_FUTURES_MARGIN_PCT = 0.30
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 5  # keep contract cap out of the way

        # MES margin = $1,320/contract (see _FUTURES_MARGIN_BY_ROOT).
        # equity chosen so 1 contract's margin is EXACTLY 30% of equity.
        equity_at_limit = 1_320.0 / 0.30

        safety = SafetyLayer(settings)
        # Neutralize the (earlier-running) drawdown check: without this, the
        # SafetyLayer's INITIAL_CAPITAL-seeded equity_peak (default $10,000)
        # would itself register as a >10% drawdown against the much smaller
        # equity_at_limit and reject the order before the margin check ever
        # runs, masking the assertion under test.
        safety._equity_peak = equity_at_limit
        at_limit = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=1_320.0,
        )
        result = safety.check_order(at_limit, equity_at_limit)
        assert result.approved is True

        safety2 = SafetyLayer(settings)
        safety2._equity_peak = equity_at_limit
        result2 = safety2.check_order(at_limit, equity_at_limit - 1.0)
        assert result2.approved is False
        assert "margin" in (result2.rejection_reason or "").lower()

    def test_margin_gate_survives_estimated_value_manipulation(self, mock_settings):
        """Attacker sets a near-zero estimated_value hoping the margin gate
        reads that field instead of computing margin from the symbol/quantity
        table. It does not — the margin table lookup is independent of
        whatever value the caller claims, so this must still be rejected.

        PRB-22 (2026-07-29): was MGC until SafetyLayer._check_paper_config_enabled
        was added to check_order() — MGC now carries paper_config.enabled=False
        (backtest/paper_config.py) and would be rejected before ever reaching
        the margin check this test exists to exercise. M2K has no PAPER_CONFIGS
        entry at all, so it clears the new gate; the 90% utilization figure
        below (vs. the prior 140%) still comfortably breaches the 30% cap.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_FUTURES_MARGIN_PCT = 0.30
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        safety = SafetyLayer(settings)
        safety._equity_peak = 2_000.0  # neutralize the drawdown check (see note above)

        # M2K margin = $900/contract; 2 contracts = $1,800 margin against a
        # $2,000 account = 90% utilization, but estimated_value claims $0.01.
        order = OrderRequest(
            symbol="M2K",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=0.01,
        )
        result = safety.check_order(order, 2_000.0)
        assert result.approved is False
        assert "margin" in (result.rejection_reason or "").lower()


# ---------------------------------------------------------------------------
# Rail 6 — the order-rate throttle (10 orders/minute)
# ---------------------------------------------------------------------------


class TestOrderRateThrottleRedTeam:
    def test_throttle_is_global_not_evaded_by_symbol_rotation(self, mock_settings):
        """Attacker rotates through a different symbol on every order,
        hoping the throttle is (incorrectly) keyed per-symbol rather than
        globally across all orders. It is global — the 11th order across
        10 distinct symbols must still be blocked.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_ORDERS_PER_MINUTE = 10
        safety = SafetyLayer(settings)

        for i in range(10):
            order = OrderRequest(
                symbol=f"SYM{i}",
                quantity=1,
                order_type="market",
                estimated_value=100.0,
            )
            result = safety.check_order(order, 100_000.0)
            assert result.approved is True

        eleventh = OrderRequest(
            symbol="SYM10", quantity=1, order_type="market", estimated_value=100.0
        )
        result = safety.check_order(eleventh, 100_000.0)
        assert result.approved is False
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.ANOMALOUS_ORDER_RATE

    def test_throttled_kill_switch_blocks_subsequent_attempts_of_any_size(
        self, mock_settings
    ):
        """After the rate throttle latches the kill switch, further attempts
        of varying (including tiny) size must all stay blocked."""
        settings = _armed_settings(mock_settings)
        settings.MAX_ORDERS_PER_MINUTE = 3
        safety = SafetyLayer(settings)

        order = OrderRequest(
            symbol="MES", quantity=1, order_type="market", estimated_value=100.0
        )
        for _ in range(3):
            assert safety.check_order(order, 100_000.0).approved is True

        for value in (100_000.0, 1.0, 0.01):
            probe = OrderRequest(
                symbol="MES", quantity=1, order_type="market", estimated_value=value
            )
            result = safety.check_order(probe, 100_000.0)
            assert result.approved is False


# ---------------------------------------------------------------------------
# Rail 7 — consecutive-loss size-reduction ladder
#   3 -> half-size, 5 -> quarter-size, 7 -> halt
# ---------------------------------------------------------------------------


class TestConsecutiveLossLadderRedTeam:
    """Uses a REAL ConsecutiveLossTracker (not a mock) wired into SafetyLayer
    so the actual multiplier math runs, isolated to a tmp_path data dir so no
    shared engine/data/loss_tracker.json state leaks between tests.

    Losses are recorded directly via tracker.record_trade() rather than
    SafetyLayer.record_trade_result() to avoid confounding these assertions
    with the separate re-entry-lockout mechanism record_trade_result() also
    sets on a loss (that mechanism is exercised by the existing safety suite).
    """

    def _tracker(self, tmp_path: Path) -> ConsecutiveLossTracker:
        return ConsecutiveLossTracker(
            data_dir=tmp_path,
            consecutive_loss_half_size=3,
            consecutive_loss_quarter_size=5,
            consecutive_loss_halt=7,
        )

    def test_three_losses_halves_position_size_even_for_large_requested_qty(
        self, mock_settings, tmp_path
    ):
        """Attacker requests a large quantity right after the 3rd consecutive
        loss, hoping to get the full size through. The ladder must still cut
        it to half, regardless of how large the request was.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 20
        settings.MAX_FUTURES_MARGIN_PCT = 0.90
        # Time-of-day independence: the ladder's own size-reduction is what
        # this test targets, not the separate after-15:00-CT overnight cap
        # (default 1 contract) — without this override the assertion is
        # masked by OVERNIGHT_LIMIT whenever CI happens to run after 3pm CT.
        settings.MAX_OVERNIGHT_CONTRACTS = 20
        tracker = self._tracker(tmp_path)
        for _ in range(3):
            tracker.record_trade("MES", -100.0)
        safety = SafetyLayer(settings, loss_tracker=tracker)

        order = OrderRequest(
            symbol="MES",
            quantity=10,
            order_type="market",
            is_futures=True,
            estimated_value=13_200.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True
        assert result.adjusted_order is not None
        assert result.adjusted_order.quantity == 5  # 10 * 0.5

    def test_five_losses_quarters_position_size(self, mock_settings, tmp_path):
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 20
        settings.MAX_FUTURES_MARGIN_PCT = 0.90
        settings.MAX_OVERNIGHT_CONTRACTS = 20  # see time-of-day note above
        tracker = self._tracker(tmp_path)
        for _ in range(5):
            tracker.record_trade("MES", -100.0)
        safety = SafetyLayer(settings, loss_tracker=tracker)

        order = OrderRequest(
            symbol="MES",
            quantity=8,
            order_type="market",
            is_futures=True,
            estimated_value=10_560.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True
        assert result.adjusted_order is not None
        assert result.adjusted_order.quantity == 2  # 8 * 0.25

    def test_seven_losses_halts_regardless_of_requested_quantity(
        self, mock_settings, tmp_path
    ):
        """Once halted, no requested size — small or large — should be
        allowed through. The halt must dominate the size-reduction ladder.
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 20
        settings.MAX_FUTURES_MARGIN_PCT = 0.90
        settings.MAX_OVERNIGHT_CONTRACTS = 20  # see time-of-day note above
        tracker = self._tracker(tmp_path)
        for _ in range(7):
            tracker.record_trade("MES", -100.0)
        safety = SafetyLayer(settings, loss_tracker=tracker)

        for qty in (1, 2, 20):
            order = OrderRequest(
                symbol="MES",
                quantity=qty,
                order_type="market",
                is_futures=True,
                estimated_value=1_320.0 * qty,
            )
            result = safety.check_order(order, 100_000.0)
            assert result.approved is False
            assert "consecutive loss" in (result.rejection_reason or "").lower()

    def test_halt_is_global_not_evaded_by_switching_to_a_fresh_symbol(
        self, mock_settings, tmp_path
    ):
        """Attacker racks up 7 consecutive losses on MES, then tries a
        symbol that has never lost a single trade (M2K), hoping the halt is
        scoped per-symbol. The halt tracks GLOBAL consecutive losses, so a
        never-traded symbol must be blocked too.

        PRB-22 (2026-07-29): was MGC until SafetyLayer._check_paper_config_enabled
        was added to check_order() — MGC now carries paper_config.enabled=False
        (backtest/paper_config.py) and would be rejected there first, which
        would make this test pass for the WRONG reason (paper_config, not the
        global consecutive-loss halt this test exists to prove). M2K has no
        PAPER_CONFIGS entry at all and, being a symbol nobody has ever traded
        in this fixture, still satisfies "never lost a single trade".
        """
        settings = _armed_settings(mock_settings)
        settings.MAX_CONTRACTS_PER_INSTRUMENT = 20
        settings.MAX_FUTURES_MARGIN_PCT = 0.90
        tracker = self._tracker(tmp_path)
        for _ in range(7):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses("M2K") == 0  # never lost on M2K
        safety = SafetyLayer(settings, loss_tracker=tracker)

        order = OrderRequest(
            symbol="M2K",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=900.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "consecutive loss" in (result.rejection_reason or "").lower()
