"""Tests for agents.strategy_metrics — informational-only helpers threading
gate-v2 verdicts and recent-trade risk metrics into LLM prompts.

Both functions under test must NEVER raise (any internal failure degrades to
`None`) since they sit on the trade-decision hot path. `compute_recent_risk_metrics`
must reuse the canonical `backtest.metrics` formulas exactly — this file locks
that invariant with a numeric-equality check rather than a shape-only assertion.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.strategy_metrics import (
    IV_RANK_HIGH_THRESHOLD,
    IV_RANK_LOW_THRESHOLD,
    MIN_TRADES_FOR_RISK_METRICS,
    compute_recent_risk_metrics,
    get_gate_v2_metrics,
    get_iv_rank,
)
from backtest.metrics import calculate_metrics
from backtest.trade_manager import BacktestResult, Trade


# --------------------------------------------------------------------------- #
# compute_recent_risk_metrics                                                 #
# --------------------------------------------------------------------------- #


def _synthetic_pnls(n: int = 15) -> list[float]:
    # Deterministic mixed win/loss series — not all-positive or all-negative
    # so std != 0 and Sharpe/Sortino are well-defined.
    base = [120.0, -60.0, 80.0, -40.0, 150.0, -30.0, 90.0, -70.0, 60.0, -50.0]
    out = (base * ((n // len(base)) + 1))[:n]
    return out


class TestComputeRecentRiskMetrics:
    def test_insufficient_trades_returns_none(self):
        pnls = _synthetic_pnls(MIN_TRADES_FOR_RISK_METRICS - 1)
        trades = [{"pnl": p} for p in pnls]
        assert compute_recent_risk_metrics(trades, 10_000.0) is None

    def test_empty_list_returns_none(self):
        assert compute_recent_risk_metrics([], 10_000.0) is None

    def test_non_positive_capital_returns_none(self):
        trades = [{"pnl": p} for p in _synthetic_pnls(15)]
        assert compute_recent_risk_metrics(trades, 0.0) is None
        assert compute_recent_risk_metrics(trades, -100.0) is None

    def test_malformed_trade_never_raises(self):
        # Missing pnl/realized_pnl entirely, and a non-numeric value — must
        # degrade to None, not raise, per the "never blocks a decision" contract.
        trades = [{"foo": "bar"}] * 10 + [{"pnl": "not-a-number"}] * 5
        assert compute_recent_risk_metrics(trades, 10_000.0) is None

    def test_realized_pnl_key_supported(self):
        pnls = _synthetic_pnls(15)
        trades = [{"realized_pnl": p} for p in pnls]
        result = compute_recent_risk_metrics(trades, 10_000.0)
        assert result is not None
        assert result["n_trades"] == 15

    def test_reproduces_canonical_metrics_formula(self):
        """Locks the 'one formula, reused' invariant: compute_recent_risk_metrics
        must return numbers identical (within float tolerance) to calling
        backtest.metrics.calculate_metrics directly on an equivalent
        BacktestResult built the same way.
        """
        pnls = _synthetic_pnls(15)
        initial_capital = 10_000.0
        trades_input = [{"pnl": p} for p in pnls]

        result = compute_recent_risk_metrics(trades_input, initial_capital)
        assert result is not None

        # Build the equivalent BacktestResult by hand and call the canonical
        # function directly — same equity-curve construction as the module
        # under test (post-trade equity snapshots, no flat non-trade bars).
        trades = [
            Trade(
                entry_date=datetime.now(),
                symbol="",
                direction="long" if pnl >= 0 else "short",
                entry_price=0.0,
                stop_price=0.0,
                target_1=0.0,
                target_2=0.0,
                contracts=1,
                multiplier=1.0,
                pnl=pnl,
            )
            for pnl in pnls
        ]
        equity_curve = [initial_capital]
        running = initial_capital
        for pnl in pnls:
            running += pnl
            equity_curve.append(running)

        expected = BacktestResult(
            symbol="",
            start_date="",
            end_date="",
            initial_capital=initial_capital,
            final_capital=equity_curve[-1],
            trades=trades,
            equity_curve=equity_curve,
        )
        calculate_metrics(expected)

        assert result["sharpe_ratio"] == pytest.approx(expected.sharpe_ratio, abs=1e-9)
        assert result["sortino_ratio"] == pytest.approx(expected.sortino_ratio, abs=1e-9)
        assert result["calmar_ratio"] == pytest.approx(expected.calmar_ratio, abs=1e-9)
        assert result["max_drawdown_pct"] == pytest.approx(expected.max_drawdown_pct, abs=1e-9)
        assert result["win_rate"] == pytest.approx(expected.win_rate, abs=1e-9)
        assert result["profit_factor"] == pytest.approx(expected.profit_factor, abs=1e-9)


# --------------------------------------------------------------------------- #
# get_gate_v2_metrics                                                         #
# --------------------------------------------------------------------------- #


def _write_verdict(
    dir_: Path,
    *,
    symbol: str,
    family: str = "trend",
    rank: int = 1,
    verdict: str = "PASS",
    passed_via: str | None = "alt",
    age_days: float = 0.0,
    gate_v2_metrics: dict | None = None,
) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
    doc = {
        "symbol": symbol,
        "family": family,
        "rank": rank,
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if verdict == "PASS" and passed_via == "core" else "FAIL",
        "alt_verdict": "PASS" if verdict == "PASS" and passed_via == "alt" else "UNSCORED",
        "n_core_passed": 4 if passed_via == "core" else 2,
        "n_alt_passed": 5 if passed_via == "alt" else 0,
        "created_at": ts.isoformat(),
        "aux_freshness": {"rolling_wfo": None, "fixed_params": None, "cost_sweep": None},
        "gate_v2": {},
        "gate_v2_metrics": gate_v2_metrics or {},
    }
    path = dir_ / f"{symbol}_{family}_rank{rank}.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Monkeypatch gate_v2_policy's default verdicts dir to an isolated tmp path.

    get_gate_v2_metrics calls get_last_verdict(symbol) with no explicit
    verdicts_dir, so it resolves via _default_verdicts_dir() — patch that,
    matching the convention already used in test_gate_v2_policy.py.
    """
    from backtest import gate_v2_policy as policy

    monkeypatch.setattr(policy, "_default_verdicts_dir", lambda: tmp_path)
    return tmp_path


class TestGetGateV2Metrics:
    def test_no_verdict_file_returns_none(self, tmp_verdicts_dir):
        assert get_gate_v2_metrics("MES") is None

    def test_returns_flattened_fields(self, tmp_verdicts_dir):
        _write_verdict(
            tmp_verdicts_dir,
            symbol="MES",
            family="trend",
            verdict="PASS",
            passed_via="alt",
            age_days=1.0,
            gate_v2_metrics={
                "pf_ci_lower": 1.15,
                "p_edge": 0.75,
                "mc_95th_dd": 350.0,
                "mc_95th_dd_pct": 0.035,
                "dsr": 0.42,
                "wfo_consistency": "STRONG",
                "fixed_params_min_pf": 1.3,
            },
        )

        result = get_gate_v2_metrics("MES")
        assert result is not None
        assert result["symbol"] == "MES"
        assert result["verdict"] == "PASS"
        assert result["passed_via"] == "alt"
        assert result["pf_ci_lower"] == 1.15
        assert result["p_edge"] == 0.75
        assert result["mc_95th_dd_pct"] == 0.035
        assert result["dsr"] == 0.42
        assert result["wfo_consistency"] == "STRONG"
        assert result["fixed_params_min_pf"] == 1.3
        assert result["age_days"] == pytest.approx(1.0, abs=0.1)

    def test_stale_verdict_returns_none(self, tmp_verdicts_dir):
        # MAX_VERDICT_AGE_DAYS is 14 — a 30-day-old verdict must be treated
        # as missing, matching get_last_verdict's staleness semantics.
        _write_verdict(tmp_verdicts_dir, symbol="MGC", age_days=30.0)
        assert get_gate_v2_metrics("MGC") is None

    def test_case_insensitive_symbol_lookup(self, tmp_verdicts_dir):
        _write_verdict(tmp_verdicts_dir, symbol="MES", age_days=0.5)
        assert get_gate_v2_metrics("mes") is not None

    def test_insufficient_sample_verdict_is_not_none(self, tmp_verdicts_dir):
        # INSUFFICIENT_SAMPLE (Init 2B) is a valid non-PASS verdict — the
        # wrapper must surface it (not silently swallow) so the LLM sees it.
        _write_verdict(
            tmp_verdicts_dir,
            symbol="MNQ",
            verdict="INSUFFICIENT_SAMPLE",
            passed_via=None,
            age_days=0.5,
        )
        result = get_gate_v2_metrics("MNQ")
        assert result is not None
        assert result["verdict"] == "INSUFFICIENT_SAMPLE"

    def test_no_verdicts_dir_at_all_returns_none(self, tmp_path, monkeypatch):
        # Directory doesn't exist on disk at all — get_last_verdict handles
        # this internally; confirm the wrapper still degrades to None.
        from backtest import gate_v2_policy as policy

        monkeypatch.setattr(
            policy, "_default_verdicts_dir", lambda: tmp_path / "does_not_exist"
        )
        assert get_gate_v2_metrics("MES") is None


# --------------------------------------------------------------------------- #
# get_iv_rank                                                                  #
# --------------------------------------------------------------------------- #


class TestGetIvRank:
    """`get_iv_rank` is a thin wrapper over `options.chain_fetcher.get_iv_rank` —
    these tests mock that underlying call rather than re-deriving the IVR math,
    matching the "reuse, don't reimplement" contract in the docstring.
    """

    def _patch_underlying(self, monkeypatch, return_value=None, side_effect=None):
        import options.chain_fetcher as chain_fetcher

        def _fake(symbol, data_manager=None, **kwargs):
            if side_effect is not None:
                raise side_effect
            return return_value

        monkeypatch.setattr(chain_fetcher, "get_iv_rank", _fake)

    def test_blank_symbol_returns_none(self):
        assert get_iv_rank("") is None
        assert get_iv_rank(None) is None
        assert get_iv_rank("   ") is None

    def test_high_iv_rank_yields_elevated_interpretation(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=85.0)
        result = get_iv_rank("MES")
        assert result is not None
        assert result["symbol"] == "MES"
        assert result["iv_rank"] == 85.0
        assert "elevated" in result["interpretation"].lower()
        assert "premium-selling" in result["interpretation"].lower()

    def test_low_iv_rank_yields_low_interpretation(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=12.0)
        result = get_iv_rank("MGC")
        assert result is not None
        assert result["iv_rank"] == 12.0
        assert "low" in result["interpretation"].lower()
        assert "premium-buying" in result["interpretation"].lower()

    def test_mid_range_iv_rank_yields_neutral_interpretation(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=50.0)
        result = get_iv_rank("MES")
        assert result is not None
        assert "neutral" in result["interpretation"].lower()

    def test_high_threshold_boundary_is_inclusive(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=IV_RANK_HIGH_THRESHOLD)
        result = get_iv_rank("MES")
        assert result is not None
        assert "elevated" in result["interpretation"].lower()

    def test_low_threshold_boundary_is_inclusive(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=IV_RANK_LOW_THRESHOLD)
        result = get_iv_rank("MES")
        assert result is not None
        assert "low" in result["interpretation"].lower()

    def test_underlying_raises_returns_none(self, monkeypatch):
        self._patch_underlying(monkeypatch, side_effect=RuntimeError("no chain data"))
        assert get_iv_rank("MES") is None

    def test_underlying_returns_none_propagates_none(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=None)
        assert get_iv_rank("MES") is None

    def test_symbol_is_uppercased_and_stripped(self, monkeypatch):
        self._patch_underlying(monkeypatch, return_value=85.0)
        result = get_iv_rank("  mes  ")
        assert result is not None
        assert result["symbol"] == "MES"

    def test_import_error_never_raises(self, monkeypatch):
        # Simulate the options module being unavailable entirely — must
        # degrade to None, not raise, per the "never blocks a decision"
        # contract shared with get_gate_v2_metrics/compute_recent_risk_metrics.
        import agents.strategy_metrics as strategy_metrics

        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "options.chain_fetcher":
                raise ImportError("simulated missing module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        assert strategy_metrics.get_iv_rank("MES") is None
