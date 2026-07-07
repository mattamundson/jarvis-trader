"""Regression guard: NO per-strategy gate runner may compute its Deflated Sharpe
by calling ``deflated_sharpe_ratio(...)`` directly.

The legacy path fed the Bailey/Lopez de Prado deflation the arithmetic MEAN of
per-window Sharpes (a 1-2 trade window yields a Sharpe of 80+), producing a
Phi(z) that rounds to 1.0 and auto-passes both gate floors. The honest path is
``_gate_v2_trade_metrics.trade_level_dsr`` (which internally uses
``deflated_sharpe_from_returns`` on the real concatenated per-trade series).

Therefore the contract for every ``run_*.py`` gate runner is simple and static:
it must NOT reference ``deflated_sharpe_ratio`` at all -- if it needs a DSR it
goes through ``trade_level_dsr``. This complements the functional fixtures in
``test_old_runners_use_trade_level_dsr.py`` and catches any NEW runner that
copy-pastes the old hack.

Run:  cd engine && .venv/Scripts/python backtest/test_no_runner_uses_window_sharpe_dsr.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BT = Path(__file__).resolve().parent
_ANTIPATTERN = "deflated_sharpe_ratio"


def _runner_files() -> list[Path]:
    return sorted(_BT.glob("run_*.py"))


def test_no_runner_calls_deflated_sharpe_ratio_directly():
    offenders = []
    for f in _runner_files():
        text = f.read_text(encoding="utf-8")
        if _ANTIPATTERN in text:
            # report line numbers for a useful failure message
            lines = [i + 1 for i, ln in enumerate(text.splitlines()) if _ANTIPATTERN in ln]
            offenders.append(f"{f.name}:{lines}")
    assert not offenders, (
        f"{len(offenders)} gate runner(s) still reference {_ANTIPATTERN!r} (the "
        "mean-of-window-Sharpes DSR hack). Route DSR through "
        "_gate_v2_trade_metrics.trade_level_dsr instead:\n  " + "\n  ".join(offenders)
    )


def test_runners_that_gate_use_trade_level_dsr():
    """Any runner that computes a `dsr` must source it from trade_level_dsr."""
    offenders = []
    for f in _runner_files():
        text = f.read_text(encoding="utf-8")
        defines_dsr = "\n    dsr =" in text or "\n        dsr =" in text
        if defines_dsr and "trade_level_dsr" not in text:
            offenders.append(f.name)
    assert not offenders, "runner(s) assign `dsr` without using trade_level_dsr:\n  " + "\n  ".join(
        offenders
    )


def main() -> int:
    tests = [
        test_no_runner_calls_deflated_sharpe_ratio_directly,
        test_runners_that_gate_use_trade_level_dsr,
    ]
    failures = []
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except AssertionError as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    print("=" * 60)
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)}")
        return 1
    print(
        f"ALL {len(tests)} static DSR-guard tests PASSED ({len(_runner_files())} runners scanned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
