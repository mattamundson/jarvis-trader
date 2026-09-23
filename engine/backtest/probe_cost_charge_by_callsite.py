"""Measure where cost is actually charged on the capital ledger, by call site.

Why this exists (2026-09-17): two successive *predictions* of the `sum(trade.pnl)`
vs `final_capital - initial_capital` gap were wrong. The first (PR #863) blamed
"entry commission + entry spread"; the second blamed a uniform "4x commission per
contract". Both were inferred from reading code paths, and both failed against the
measured $1,748.12 gap on the MES VIX-percentile full sample (the second
over-predicted by 2x). Inference from PF shape and from a single exit-type fixture
is not evidence.

This script stops predicting: it subclasses `Backtester` to record every
`_transaction_cost` and `_exit_spread_cost` call, attributing each charge to the
caller frame (`_process_pending_entry`, `_check_targets_exit`, `_process_stop`,
`run` EOD block, ...). Output is the real per-path cost decomposition, which is
what the economics report must cite.

Run from `engine/`:
    env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' \
        .venv/Scripts/python.exe backtest/probe_cost_charge_by_callsite.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

import backtest.backtester as backtester_module  # noqa: E402
from backtest.analyze_mes_vix_pctile_economics import (  # noqa: E402
    DEEP_CACHE_HINT,
    _load_mes_data,
    _load_vix_data,
    _run_signals_and_backtest,
)


def _caller_name() -> str:
    """Name of the business-logic function that called the cost hook.

    Frame stack: _caller_name(0) <- _record(1) <- overriding hook(2) <- business caller(3).
    """
    try:
        return sys._getframe(3).f_code.co_name
    except ValueError:  # pragma: no cover
        return "<unknown>"


class _ChargingBacktester(backtester_module.Backtester):  # type: ignore[misc]
    """Backtester that tallies every cost it charges, keyed by calling method."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.charges: dict[str, float] = {}
        self.charge_counts: dict[str, int] = {}

    def _record(self, kind: str, amount: float) -> None:
        key = f"{kind}@{_caller_name()}"
        self.charges[key] = self.charges.get(key, 0.0) + amount
        self.charge_counts[key] = self.charge_counts.get(key, 0) + 1

    def _transaction_cost(self, contracts: int, tick_size: float = 0.25) -> float:
        amt = super()._transaction_cost(contracts, tick_size)
        self._record("commission", amt)
        return amt

    def _exit_spread_cost(self, contracts: int, tick_size: float, multiplier: float) -> float:
        amt = super()._exit_spread_cost(contracts, tick_size, multiplier)
        self._record("exit_spread", amt)
        return amt


def main() -> int:
    data_dir = engine_root / "backtest" / "cache"
    cache_path = data_dir / DEEP_CACHE_HINT
    if not cache_path.exists():
        print(f"ERROR: deep cache not found: {cache_path}")
        return 2
    df = _load_mes_data(data_dir)
    # Guard the exact failure mode recorded in the JARVIS rules: a fresh worktree can
    # silently select a shallow 2.2y cache. Refuse to report cost decomposition for a
    # sample that cannot certify the strategy.
    if len(df) < 40_000:
        print(f"ERROR: selected cache has only {len(df)} bars — that is the shallow cache, not "
              f"the 43,010-bar deep one. Aborting rather than reporting a misleading decomposition.")
        return 4
    vix_df = _load_vix_data(start=str(df.index.min().date()))
    print(f"deep cache: {DEEP_CACHE_HINT}  bars={len(df)}  span={df.index.min()} -> {df.index.max()}")

    captured: dict[str, _ChargingBacktester] = {}
    original = backtester_module.Backtester

    class _Capture(_ChargingBacktester):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["bt"] = self

    # `_run_signals_and_backtest` does `from backtest.backtester import Backtester`
    # inside the function body, so patching the source module's attribute is the hook.
    backtester_module.Backtester = _Capture
    try:
        result = _run_signals_and_backtest(df, vix_df, ())
    finally:
        backtester_module.Backtester = original

    bt = captured.get("bt")
    if bt is None:
        print("ERROR: instrumented Backtester was never constructed")
        return 3

    trades = result.trades
    ledger = float(sum(t.pnl for t in trades))
    equity = float(result.final_capital - result.initial_capital)
    gap = ledger - equity
    sum_c = int(sum(t.contracts for t in trades))
    cpc = float(bt.commission_per_contract)

    print(f"\ntrades={len(trades)}  sum_contracts={sum_c}  commission_per_contract={cpc}")
    print(f"ledger sum(trade.pnl) = {ledger:+.2f}")
    print(f"final_capital - initial = {equity:+.2f}")
    print(f"gap = {gap:.2f}")

    print("\n-- charged to capital, by call site (measured) --")
    commission_total = 0.0
    spread_total = 0.0
    for key in sorted(bt.charges):
        amt = bt.charges[key]
        if key.startswith("commission"):
            commission_total += amt
        else:
            spread_total += amt
        print(f"  {key:42s} {amt:10.2f}   (n={bt.charge_counts[key]})")
    print(f"  {'TOTAL commission charged':42s} {commission_total:10.2f}")
    print(f"  {'TOTAL exit_spread charged':42s} {spread_total:10.2f}")
    measured = commission_total + spread_total
    print(f"  {'TOTAL cost charged to capital':42s} {measured:10.2f}")
    print(f"\nreconciliation: gap({gap:.2f}) - measured_cost({measured:.2f}) = {gap - measured:+.2f}")
    print(f"residual as % of gap: {100 * (gap - measured) / gap:+.3f}%")
    print(f"\nimplied commission multiple vs 1x round trip (sum_c*cpc = {sum_c * cpc:.2f}): "
          f"{commission_total / (sum_c * cpc):.4f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
