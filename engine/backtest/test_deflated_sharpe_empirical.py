"""
JARVIS TRADER — Empirical DSR Unit Tests (audit fix, 2026-08-04)

Proves the MC-calibrated empirical DSR discriminates where the closed-form
DSR cannot:

1. A REALISTIC GOOD edge (PF ~1.31, 35% win rate) must PASS the empirical
   gate (DSR >= 0.30) while FAILING the closed form (DSR ~ 0.000) — the
   exact behavior that motivated the audit.
2. A COIN FLIP (no edge) must FAIL both — the empirical gate must not
   blindly pass everything.
3. Sample-size independence: the empirical null adapts so a genuinely
   strong edge passes at small AND larger samples (closed form is stuck
   at 0.000 at every size).
4. n_trials selection-bias: adding more grid combos RAISES the null bar
   (lowers DSR) — the selection-bias correction still works.

Run:  cd engine && python backtest/test_deflated_sharpe_empirical.py
"""

from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, ".")
from backtest.deflated_sharpe import (  # noqa: E402
    deflated_sharpe_empirical,
    deflated_sharpe_from_returns,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"{name}... {status}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILURES.append(name)


def _profile(pf: float, n_wins: int, n_losses: int) -> list[float]:
    """Build a trade PnL list with the given profit factor and win/loss counts."""
    loss = 1.0
    win = pf * n_losses / n_wins * loss
    return [win] * n_wins + [-loss] * n_losses


def _coinflip(n: int = 18) -> list[float]:
    rng = np.random.default_rng(7)
    return [1.0 if rng.random() < 0.5 else -1.0 for _ in range(n)]


# ── Test 1: good edge passes empirical, fails closed form ────────────────────


def test_good_edge_empirical_passes_closed_form_fails():
    pnls = _profile(pf=1.31, n_wins=7, n_losses=11)  # the real RV-filter shape

    emp = deflated_sharpe_empirical(pnls, n_trials=3, initial_capital=50_000.0)
    closed = deflated_sharpe_from_returns(
        returns=(np.asarray(pnls) / 50_000.0).tolist(), n_trials=3
    )

    check(
        "PF 1.31 edge: empirical DSR >= 0.30 (passes)",
        emp["dsr"] >= 0.30,
        f"emp_dsr={emp['dsr']:.3f}",
    )
    check(
        "PF 1.31 edge: closed-form DSR < 0.30 (the bug)",
        closed["dsr"] < 0.30,
        f"closed_dsr={closed['dsr']:.4f}",
    )
    check(
        "PF 1.31 edge: empirical > closed by a wide margin",
        emp["dsr"] - closed["dsr"] > 0.3,
        f"gap={emp['dsr'] - closed['dsr']:.3f}",
    )


# ── Test 2: coin flip fails BOTH ─────────────────────────────────────────────


def test_coinflip_fails_both():
    pnls = _coinflip(24)

    emp = deflated_sharpe_empirical(pnls, n_trials=3, initial_capital=50_000.0)
    closed = deflated_sharpe_from_returns(
        returns=(np.asarray(pnls) / 50_000.0).tolist(), n_trials=3
    )

    check(
        "coin flip: empirical DSR < 0.30 (correctly fails)",
        emp["dsr"] < 0.30,
        f"emp_dsr={emp['dsr']:.3f}",
    )
    check(
        "coin flip: empirical DSR < 0.10 (strong rejection)",
        emp["dsr"] < 0.10,
        f"emp_dsr={emp['dsr']:.3f}",
    )
    check(
        "coin flip: closed form also fails (no false pass in old gate)",
        closed["dsr"] < 0.30,
        f"closed_dsr={closed['dsr']:.4f}",
    )


# ── Test 3: sample-size independence ─────────────────────────────────────────


def test_strong_edge_passes_at_small_and_large_samples():
    for n_trades in (20, 40, 80):
        n_wins = int(n_trades * 0.35)
        n_losses = n_trades - n_wins
        pnls = _profile(pf=1.5, n_wins=n_wins, n_losses=n_losses)

        emp = deflated_sharpe_empirical(pnls, n_trials=3, initial_capital=50_000.0)
        closed = deflated_sharpe_from_returns(
            returns=(np.asarray(pnls) / 50_000.0).tolist(), n_trials=3
        )
        check(
            f"PF 1.5 at {n_trades} trades: empirical passes, closed fails",
            emp["dsr"] >= 0.30 and closed["dsr"] < 0.30,
            f"emp={emp['dsr']:.3f} closed={closed['dsr']:.4f}",
        )


# ── Test 4: n_trials selection-bias still penalizes ──────────────────────────


def test_more_trials_raises_null_bar():
    pnls = _profile(pf=1.5, n_wins=28, n_losses=52)  # 80 trades

    emp_3 = deflated_sharpe_empirical(pnls, n_trials=3, initial_capital=50_000.0)
    emp_36 = deflated_sharpe_empirical(pnls, n_trials=36, initial_capital=50_000.0)

    check(
        "searching 36 combos must penalize harder than 3",
        emp_3["dsr"] >= emp_36["dsr"],
        f"dsr_3={emp_3['dsr']:.3f} dsr_36={emp_36['dsr']:.3f}",
    )
    check(
        "null mean rises with n_trials (selection-bias modeled)",
        emp_36["null_mean_sharpe"] > emp_3["null_mean_sharpe"],
        f"null3={emp_3['null_mean_sharpe']:.3f} null36={emp_36['null_mean_sharpe']:.3f}",
    )


# ── Test 5: degenerate input fails safe ──────────────────────────────────────


def test_degenerate_input_fails_safe():
    emp = deflated_sharpe_empirical([], n_trials=3, initial_capital=50_000.0)
    check("empty trade list -> dsr 0.0 (fail-safe)", emp["dsr"] == 0.0)

    emp2 = deflated_sharpe_empirical([1.0, -1.0], n_trials=3, initial_capital=50_000.0)
    check("2 trades -> dsr 0.0 (fail-safe)", emp2["dsr"] == 0.0)


if __name__ == "__main__":
    print("=" * 60)
    print("JARVIS TRADER — Empirical DSR Unit Tests")
    print("=" * 60)
    print()

    test_good_edge_empirical_passes_closed_form_fails()
    test_coinflip_fails_both()
    test_strong_edge_passes_at_small_and_large_samples()
    test_more_trials_raises_null_bar()
    test_degenerate_input_fails_safe()

    print()
    total = 10
    passed = total - len(FAILURES)
    print(f"{passed}/{total} passed" + (f", {len(FAILURES)} FAILED: {FAILURES}" if FAILURES else ""))
    sys.exit(1 if FAILURES else 0)
