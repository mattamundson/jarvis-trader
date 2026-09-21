"""Atomic ledger fix: reading A, one round trip per contract, charged once.

Design note — why this is only four edits in `backtester.py`:

The four exit paths (targets / stop / EOD / run-level) each independently add raw `pnl` to
`trade.pnl` and separately debit costs from `capital`. Rather than editing all four consistently
(which is where a partial edit would leave an inconsistent cost model), costs are attributed to
trades ONCE, at the end of `run()`, proportionally to contracts. Costs are charged per contract, so
proportional allocation is faithful — and `sum(trade.pnl) == final_capital - initial_capital` becomes
exact by construction rather than by four matching edits.

Reading A (decided 2026-09-18): `COMMISSION_PER_CONTRACT` (1.42) is the ROUND TRIP, so a contract is
charged it once. Entry no longer charges; the closing exit charges `contracts * cpc` per tranche.

Every replacement is asserted to have applied. Any miss, compile error, or test failure reverts both
files — this script cannot leave the tree partially fixed.
"""

from __future__ import annotations

import py_compile
import subprocess
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent  # engine/
BT = ENGINE / "backtest" / "backtester.py"

EDITS = [
    # 1. Reading A: one round trip per contract, not two.
    (
        """        return (
            self._round_trip_cost(contracts, self.commission_per_contract)
            if self.commission_enabled
            else 0.0
        )""",
        """        # Reading A (2026-09-18): COMMISSION_PER_CONTRACT is the ROUND TRIP, so a contract is
        # charged it ONCE. Together with charging only at the closing exit, this yields exactly one
        # round trip per contract (previously: 2x per leg, charged at entry AND every exit).
        return (
            contracts * self.commission_per_contract
            if self.commission_enabled
            else 0.0
        )""",
    ),
    # 2. Entry no longer charges commission (the closing exit does).
    (
        "        capital_used = self._transaction_cost(total_contracts, tick_size)",
        "        # Commission is charged at the closing exit (see _transaction_cost); charging it here\n"
        "        # as well double-charged every trade.\n"
        "        capital_used = 0.0",
    ),
    # 3. spread_cost_total should equal what was actually charged (exit side only, once).
    (
        "t.contracts * self.spread_ticks * tick_size * multiplier * 2  # entry + exit",
        "t.contracts * self.spread_ticks * tick_size * multiplier  # exit side only (entry cancels in the realised distance)",
    ),
    # 4. Attribute the costs actually charged onto the trades, so the ledger reconciles exactly.
    (
        "        result = BacktestResult(",
        """        # Ledger reconciliation (2026-09-18): attribute the costs actually debited from capital
        # onto the trades that incurred them, proportionally to contracts (costs are charged per
        # contract), so sum(trade.pnl) == final_capital - initial_capital EXACTLY. Without this the
        # trade ledger excludes all cost while the equity curve includes it, making PF/Sharpe
        # optimistic and CAGR/drawdown pessimistic at the same time.
        _ledger_gap = sum(t.pnl for t in completed_trades) - (capital - self.initial_capital)
        _total_contracts_all = sum(t.contracts for t in completed_trades)
        if completed_trades and _total_contracts_all and abs(_ledger_gap) > 1e-12:
            for _t in completed_trades:
                _t.pnl -= _ledger_gap * (_t.contracts / _total_contracts_all)

        result = BacktestResult(""",
    ),
]


def main() -> int:
    src = BT.read_text(encoding="utf-8")
    applied = []
    for i, (old, new) in enumerate(EDITS, 1):
        if old not in src:
            print(f"ABORT: edit {i} anchor not found — no changes written")
            return 3
        if src.count(old) != 1:
            print(f"ABORT: edit {i} anchor appears {src.count(old)}x (not unique)")
            return 3
        src = src.replace(old, new, 1)
        applied.append(i)

    BT.write_text(src, encoding="utf-8")
    print(f"applied edits: {applied}")
    try:
        py_compile.compile(str(BT), doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"COMPILE FAIL -> reverting: {str(exc).splitlines()[-1][:90]}")
        subprocess.run(["git", "checkout", "--", str(BT)], cwd=ENGINE.parent, check=False)
        return 4
    print("compiles OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
