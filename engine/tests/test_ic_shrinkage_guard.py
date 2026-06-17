"""
IC sample-adequacy shrinkage guard tests.

Follow-up to the 2026-06-16 direction-aware calibration fix: even with the
direction bug corrected, ``get_ensemble_weights`` would concentrate ~100% of
the live sizing weight on a single analyst whose IC happened to be the only
positive one over a handful of trades (observed: 100% on ``fundamental`` at
n=8). A rank correlation estimated from ~8 points has a standard error near
0.38 -- indistinguishable from noise -- so the weights are now blended toward
equal weight by a confidence factor ``alpha`` tied to the effective sample
behind them. These tests pin that behavior.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from analytics.ic_ensemble import ICWeightedEnsemble  # noqa: E402


def _make_winner_db(path, agent, n, *, direction="LONG"):
    """Create a trade_outcomes DB where one agent's signal perfectly tracks the
    realized price direction over ``n`` rows (IC ~ 1.0); the other agents have
    NULL signals (no data -> muted). Returns nothing.
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE trade_outcomes (
            trade_id TEXT, timestamp TEXT, symbol TEXT, direction TEXT,
            pnl_usd REAL, pnl_pct REAL, outcome TEXT,
            technical_signal REAL, news_signal REAL, fundamental_signal REAL
        )"""
    )
    base = datetime.now(timezone.utc)
    col = f"{agent}_signal"
    for i in range(1, n + 1):
        ts = (base - timedelta(seconds=i * 60)).isoformat()
        # Strictly increasing signal and pnl -> Spearman rank correlation = 1.0.
        conn.execute(
            f"INSERT INTO trade_outcomes "
            f"(trade_id, timestamp, symbol, direction, pnl_usd, {col}) "
            f"VALUES (?,?,?,?,?,?)",
            (f"t{i}", ts, "MES", direction, float(i) * 10.0, float(i) / n),
        )
    conn.commit()
    conn.close()


AGENTS = ["technical", "news", "fundamental"]
EQUAL = 1.0 / len(AGENTS)


class TestSmallSampleShrinkage:
    def test_thin_sample_does_not_concentrate(self, tmp_path):
        """At n=8 the winning agent must NOT capture ~100% of the weight."""
        db = tmp_path / "fb.db"
        _make_winner_db(db, "fundamental", n=8)
        ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)

        w = ens.get_ensemble_weights()
        # Pre-guard this was ~1.0; the guard pulls it well back toward equal.
        assert w["fundamental"] < 0.5
        # ...but the winner still earns *some* edge over equal weight.
        assert w["fundamental"] > EQUAL
        # Muted agents are NOT zeroed out -- they keep their shrink share.
        assert w["technical"] > 0.20
        assert w["news"] > 0.20
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_alpha_near_zero_on_thin_sample(self, tmp_path):
        db = tmp_path / "fb.db"
        _make_winner_db(db, "fundamental", n=8)
        ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)
        d = ens.describe()
        # alpha = (8 - 1) / (40 - 1) = 0.179
        assert d["shrinkage_alpha"] == pytest.approx(7 / 39, abs=1e-3)
        assert d["effective_sample"] == pytest.approx(8.0, abs=1e-6)
        assert d["full_confidence_trades"] == 40


class TestFullSampleConfidence:
    def test_rich_sample_restores_concentration(self, tmp_path):
        """At n >= full_confidence_trades the winner gets ~undiluted IC weight."""
        db = tmp_path / "fb.db"
        _make_winner_db(db, "fundamental", n=45)
        ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)

        w = ens.get_ensemble_weights()
        assert w["fundamental"] > 0.95  # alpha clipped to 1.0 -> raw IC weight
        assert abs(sum(w.values()) - 1.0) < 1e-9

        d = ens.describe()
        assert d["shrinkage_alpha"] == pytest.approx(1.0, abs=1e-9)


class TestMonotonicConfidence:
    def test_concentration_grows_with_sample(self, tmp_path):
        """The winner's weight increases monotonically with sample size."""
        weights = []
        for n in (8, 20, 39):
            db = tmp_path / f"fb_{n}.db"
            _make_winner_db(db, "fundamental", n=n)
            ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)
            weights.append(ens.get_ensemble_weights()["fundamental"])
        assert weights[0] < weights[1] < weights[2]
        # All converge upward toward the undiluted raw weight (1.0) but stay below it.
        assert all(wt < 1.0 for wt in weights)


class TestContractPreserved:
    def test_compute_ic_unchanged_by_refactor(self, tmp_path):
        """compute_ic still returns the raw IC (delegates to _ic_with_count)."""
        db = tmp_path / "fb.db"
        _make_winner_db(db, "fundamental", n=8)
        ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)
        # Perfect rank alignment -> IC ~ 1.0, independent of the weight shrinkage.
        assert ens.compute_ic("fundamental") > 0.99
        assert ens.compute_ic("technical") == 0.0  # NULL signals -> muted

    def test_equal_weight_fallback_unchanged(self, tmp_path):
        """No positive IC anywhere -> equal weights (unchanged legacy behavior)."""
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            """CREATE TABLE trade_outcomes (
                trade_id TEXT, timestamp TEXT, symbol TEXT, direction TEXT,
                pnl_usd REAL, technical_signal REAL, news_signal REAL,
                fundamental_signal REAL
            )"""
        )
        conn.commit()
        conn.close()
        ens = ICWeightedEnsemble(db_path=str(db), agents=AGENTS, min_trades=1)
        w = ens.get_ensemble_weights()
        for a in AGENTS:
            assert w[a] == pytest.approx(EQUAL, abs=1e-9)
