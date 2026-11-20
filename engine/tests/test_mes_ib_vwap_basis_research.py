from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import pytest

from backtest.research.mes_ib_ladder import (
    ladder_event,
    simulate_simple_ib_break,
    simulate_trade,
)
from backtest.research.mes_weekly_vwap_acceptance import (
    CLASSES,
    AcceptanceRecord,
    _economics,
    _probabilities,
    label_partition,
    summarize_walk_forward,
    walk_forward_feature,
)
from backtest.research.session_data import SessionSlice, add_session_columns
from backtest.research.spx_futures_basis import BasisTranslationInput, translate_spx_strike
from backtest.research.verify_mes_ib_vwap_artifacts import _sha


def _bars(start_ct: str, rows: list[tuple[float, float, float, float, float]], freq: str = "5min") -> pd.DataFrame:
    idx = pd.date_range(start_ct, periods=len(rows), freq=freq, tz="America/Chicago").tz_convert("UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _session(first_post_bar=(109.0, 111.0, 109.0, 110.5, 100.0)) -> SessionSlice:
    overnight = _bars("2026-01-04 17:00", [
        (104, 112, 103, 108, 100),
        (108, 113, 106, 109, 100),
    ])
    ib_rows = []
    for i in range(12):
        low = 100.0 if i == 0 else 102.0
        high = 110.0 if i == 11 else 108.0
        ib_rows.append((104.0, high, low, 105.0, 100.0))
    ib = _bars("2026-01-05 08:30", ib_rows)
    post = _bars("2026-01-05 09:30", [
        first_post_bar,
        (110.5, 116.0, 109.0, 115.0, 100.0),
        (115.0, 121.0, 114.0, 120.0, 100.0),
    ])
    rth = pd.concat([ib, post])
    return SessionSlice(date(2026, 1, 5), overnight, rth, ib, post)


class TestIBLadder:
    def test_completed_ib_is_not_entered_before_0930(self):
        outcome = simulate_trade(
            _session(), entry_mode="stop_entry", stop_mode="ib_mid",
            target_mode="half_ib", slippage_ticks_per_side=1,
        )
        assert outcome is not None
        assert pd.Timestamp(outcome.entry_time).tz_convert("America/Chicago").time() >= time(9, 30)

    def test_ambiguous_first_break_is_excluded(self):
        session = _session((105.0, 111.0, 99.0, 105.0, 100.0))
        outcome = simulate_trade(
            session, entry_mode="stop_entry", stop_mode="ib_mid",
            target_mode="half_ib", slippage_ticks_per_side=1,
        )
        assert outcome is None
        assert ladder_event(session).ambiguous_break is True

    def test_same_bar_stop_and_target_resolves_stop_first(self):
        session = _session((110.0, 116.0, 104.0, 111.0, 100.0))
        outcome = simulate_trade(
            session, entry_mode="stop_entry", stop_mode="ib_mid",
            target_mode="half_ib", slippage_ticks_per_side=1,
        )
        assert outcome is not None
        assert outcome.exit_reason == "stop"
        assert outcome.net_pnl < 0

    def test_cost_ledger_reconciles_exactly(self):
        outcome = simulate_trade(
            _session(), entry_mode="stop_entry", stop_mode="opposite_ib",
            target_mode="ladder", slippage_ticks_per_side=1,
        )
        assert outcome is not None
        assert outcome.ledger_reconciliation_residual == 0.0
        assert outcome.net_pnl == pytest.approx(
            outcome.gross_pnl - outcome.fees - outcome.slippage_cost
        )

    def test_simple_ib_break_baseline_reconciles(self):
        outcome = simulate_simple_ib_break(_session(), slippage_ticks_per_side=2)
        assert outcome is not None
        assert outcome.config_id == "simple_ib_break__slip2"
        assert outcome.ledger_reconciliation_residual == 0.0


class TestSessionSemantics:
    def test_sunday_globex_belongs_to_monday_trade_date_and_week(self):
        df = _bars("2026-03-08 17:00", [(100, 101, 99, 100, 1)])
        tagged = add_session_columns(df)
        assert tagged.iloc[0]["trade_date"] == date(2026, 3, 9)
        assert tagged.iloc[0]["week_key"] == date(2026, 3, 9)
        assert bool(tagged.iloc[0]["is_overnight"])


class TestVWAPWalkForward:
    @staticmethod
    def _records(n: int = 100) -> list[AcceptanceRecord]:
        rows = []
        start = date(2025, 1, 1)
        outcomes = ("continuation", "rotation", "failure")
        for i in range(n):
            realized = outcomes[i % 3]
            state = bool(i % 2)
            rows.append(AcceptanceRecord(
                signal_date=str(start + timedelta(days=i)),
                decision_time_ct="10:30",
                week_key=str(start + timedelta(days=i - (start + timedelta(days=i)).weekday())),
                decision_timestamp=datetime(2025, 1, 1, 16, tzinfo=timezone.utc).isoformat(),
                decision_price=100.0,
                weekly_vwap=99.0,
                session_close=100.0,
                session_low=98.0,
                next_close=101.0 if realized == "continuation" else 99.0,
                next_low=97.0 if realized == "failure" else 99.0,
                realized=realized,
                baseline_above_vwap=state,
                time_acceptance=state,
                volume_acceptance=state,
                developing_vpoc_acceptance=state,
                developing_tpo_poc_acceptance=state,
                clv_delta_proxy_acceptance=state,
                volume_fraction_above_vwap=0.7 if state else 0.3,
                developing_vpoc=100.0,
                developing_tpo_poc=100.0,
                clv_delta_proxy=1.0 if state else -1.0,
            ))
        return rows

    def test_outcome_partition_is_mutually_exclusive(self):
        assert label_partition(101, 95, 100, 98) == "continuation"
        assert label_partition(99, 97, 100, 98) == "failure"
        assert label_partition(99, 98, 100, 98) == "rotation"

    def test_probabilities_sum_to_one(self):
        probs = _probabilities(self._records(9))
        assert set(probs) == set(CLASSES)
        assert sum(probs.values()) == pytest.approx(1.0)

    def test_future_tampering_does_not_change_prior_predictions(self):
        records = self._records(110)
        clean = walk_forward_feature(records, "time", min_train=20, min_state_train=5)
        tampered = list(records)
        for i in range(90, len(tampered)):
            row = tampered[i]
            tampered[i] = AcceptanceRecord(**{
                **row.__dict__,
                "realized": "failure" if row.realized != "failure" else "continuation",
                "next_close": row.next_close * 2,
                "next_low": row.next_low / 2,
            })
        after = walk_forward_feature(tampered, "time", min_train=20, min_state_train=5)
        clean_by_key = {(r["signal_date"], r["decision_time_ct"]): r for r in clean}
        for row in after:
            key = (row["signal_date"], row["decision_time_ct"])
            if key in clean_by_key and row["signal_date"] < records[88].signal_date:
                assert row["p_model"] == clean_by_key[key]["p_model"]
                assert row["p_baseline"] == clean_by_key[key]["p_baseline"]

    def test_identical_feature_and_baseline_not_retained(self):
        rows = walk_forward_feature(self._records(110), "time", min_train=20, min_state_train=5)
        summary = summarize_walk_forward(rows)
        assert summary["paired_diff_baseline_minus_model"] == pytest.approx(0.0)
        assert summary["retained"] is False

    def test_pooled_economics_never_triple_counts_one_session(self):
        rows = [
            {
                "signal_date": "2026-01-05",
                "decision_time_ct": decision,
                "feature_state": True,
                "session_close": 100.0,
                "next_close": 101.0,
            }
            for decision in ("10:30", "11:30", "12:30")
        ]
        summary = _economics(rows, "feature_state")
        assert summary["n_trades"] == 1
        assert summary["unique_signal_dates"] == 1


class TestBasisTranslator:
    def _base(self, **overrides):
        values = {
            "spx_strike": 7750.0,
            "spx_spot": 7750.0,
            "risk_free_rate": 0.045,
            "dividend_yield": 0.012,
            "valuation_time": datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
            "spot_timestamp": datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
            "contract_symbol": "ESZ6",
            "contract_expiry": date(2026, 12, 18),
        }
        values.update(overrides)
        return BasisTranslationInput(**values)

    def test_theoretical_translation_is_in_loom_region(self):
        result = translate_spx_strike(self._base())
        assert result.basis_source == "theoretical_carry"
        assert 7800 <= result.translated_level <= 7825
        assert result.original_spx_strike == 7750

    def test_fresh_observed_basis_takes_precedence(self):
        result = translate_spx_strike(self._base(
            observed_futures_price=7810.0,
            observed_futures_timestamp=datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
        ))
        assert result.basis_source == "observed_synchronized_basis"
        assert result.observed_basis == 60.0
        assert result.translated_level == 7810.0

    def test_stale_observed_basis_is_rejected(self):
        result = translate_spx_strike(self._base(
            observed_futures_price=7900.0,
            observed_futures_timestamp=datetime(2026, 9, 25, 16, 50, tzinfo=timezone.utc),
        ))
        assert result.basis_source == "theoretical_carry"
        assert result.stale_observed_basis_rejected is True

    def test_stale_spot_fails_closed(self):
        with pytest.raises(ValueError, match="spot is stale"):
            translate_spx_strike(self._base(
                spot_timestamp=datetime(2026, 9, 25, 16, 50, tzinfo=timezone.utc)
            ))

    def test_es_and_mes_share_price_level(self):
        observed = {
            "observed_futures_price": 7810.0,
            "observed_futures_timestamp": datetime(2026, 9, 25, 17, tzinfo=timezone.utc),
        }
        es = translate_spx_strike(self._base(output_symbol="ES", **observed))
        mes = translate_spx_strike(self._base(output_symbol="MES", **observed))
        assert es.translated_level == mes.translated_level
        assert es.output_symbol != mes.output_symbol

    def test_expired_contract_rejected_and_roll_window_flagged(self):
        with pytest.raises(ValueError, match="expired"):
            translate_spx_strike(self._base(contract_expiry=date(2026, 9, 1)))
        roll = translate_spx_strike(self._base(
            valuation_time=datetime(2026, 12, 12, tzinfo=timezone.utc),
            spot_timestamp=datetime(2026, 12, 12, tzinfo=timezone.utc),
        ))
        assert roll.in_roll_window is True


def test_artifact_hash_is_line_ending_invariant(tmp_path) -> None:
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "verified": true\n}\n')
    crlf.write_bytes(b'{\r\n  "verified": true\r\n}\r\n')

    assert _sha(lf) == _sha(crlf)
