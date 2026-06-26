"""R2/T9: beta-harvest gate-verdict routing (Tier-3, T10-approved 2026-06-25).

The verdict math (gate_v2_beta_harvest_verdict) is covered by the mechanism's own
53 tests. These tests cover only the ROUTING: a beta_harvest-tagged strategy's
verdict goes through the variant when (and only when) the gate is enforced, every
other read is unchanged, and routing the verdict NEVER promotes.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

import backtest.live_promotion_gate as lpg  # noqa: E402
import backtest.session_anomaly_backtest as sab  # noqa: E402


def _stub_verdicts(monkeypatch):
    # resolve_gate_verdict lazily imports these from sab at call time, so patching
    # the module attributes is sufficient.
    monkeypatch.setattr(
        sab, "gate_v2_verdict", lambda r, **k: {"verdict": "FAIL", "route": "canonical"}
    )
    monkeypatch.setattr(
        sab,
        "gate_v2_beta_harvest_verdict",
        lambda r, **k: {"verdict": "PASS", "route": "beta", "beta_harvest": True},
    )


# ── the enforcement flag ────────────────────────────────────────────────────────────


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("BETA_HARVEST_GATE_ENFORCE", raising=False)
    assert lpg.beta_harvest_gate_enforced() is False


def test_flag_truthy_values(monkeypatch):
    for v in ("1", "true", "on", "YES", "True"):
        monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", v)
        assert lpg.beta_harvest_gate_enforced() is True


def test_flag_falsey_values(monkeypatch):
    for v in ("0", "false", "off", "no", ""):
        monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", v)
        assert lpg.beta_harvest_gate_enforced() is False


# ── routing ─────────────────────────────────────────────────────────────────────────


def test_tagged_routes_to_beta_when_enforced(monkeypatch):
    _stub_verdicts(monkeypatch)
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    out = lpg.resolve_gate_verdict(object(), strategy_class="beta_harvest")
    assert out["route"] == "beta"
    assert out["verdict"] == "PASS"


def test_tagged_unchanged_when_flag_off(monkeypatch):
    _stub_verdicts(monkeypatch)
    monkeypatch.delenv("BETA_HARVEST_GATE_ENFORCE", raising=False)
    out = lpg.resolve_gate_verdict(object(), strategy_class="beta_harvest")
    assert out["route"] == "canonical"  # approved but not activated -> canonical


def test_untagged_always_canonical_even_when_enforced(monkeypatch):
    _stub_verdicts(monkeypatch)
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    out = lpg.resolve_gate_verdict(object(), strategy_class="")
    assert out["route"] == "canonical"


# ── safety: routing the verdict does NOT promote ────────────────────────────────────


def test_routing_does_not_promote_tom(monkeypatch):
    # Even with the gate enforced, turn-of-month stays BLOCKED on the independent
    # pillars (robust_edge / paper_shadow / live_system_stable). Routing the gate
    # verdict is not a promotion.
    monkeypatch.setenv("BETA_HARVEST_GATE_ENFORCE", "1")
    res = lpg.evaluate_promotion(lpg.turn_of_month_current_evidence())
    assert res["promote"] is False
    assert "robust_edge" in res["blocks"]
    assert "paper_shadow_passed" in res["blocks"]
    assert "live_system_stable" in res["blocks"]
