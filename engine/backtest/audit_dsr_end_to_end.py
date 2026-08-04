"""
DSR Audit — end-to-end verification against REAL OOS trade data.

Runs the actual MES RV-filter rank2 WFO gate machinery with the DSR function
instrumented to log its real inputs (raw Sharpe, n_obs, n_trials, skew, kurt,
expected-max null, std error, final DSR) so we can prove whether the gate's
deflation is rejecting a real edge or structurally unable to pass any
trade-based return series.

Usage:
    cd engine && python backtest/audit_dsr_end_to_end.py
"""

from __future__ import annotations

import sys
from pathlib import Path

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ── Instrument the DSR function BEFORE importing the runner ─────────────────
import backtest.deflated_sharpe as ds_module

_original = ds_module.deflated_sharpe_from_returns

AUDIT_LOG: list[dict] = []


def _instrumented(returns, n_trials: int, ann_factor: float = 252.0) -> dict:
    result = _original(returns, n_trials, ann_factor=ann_factor)
    import numpy as np

    r = np.asarray(returns, dtype=float)
    n_obs = len(r)
    mean = float(r.mean()) if n_obs else 0.0
    std = float(r.std(ddof=1)) if n_obs > 1 else 0.0
    raw_sharpe = mean / std if std > 0 else 0.0
    skew = float(__import__("scipy.stats", fromlist=["skew"]).skew(r)) if n_obs > 2 else 0.0
    kurt = float(__import__("scipy.stats", fromlist=["kurtosis"]).kurtosis(r, fisher=False)) if n_obs > 2 else 3.0
    entry = {
        "n_obs": n_obs,
        "n_trials": n_trials,
        "mean_ret": round(mean, 6),
        "std_ret": round(std, 6),
        "raw_sharpe": round(raw_sharpe, 6),
        "skew": round(skew, 6),
        "kurt": round(kurt, 6),
        "result_dsr": result.get("dsr"),
        "result_raw_sharpe": result.get("raw_sharpe"),
        "expected_max": result.get("expected_max_sharpe"),
        "sharpe_std_error": result.get("sharpe_std_error"),
        "n_positive": int((r > 0).sum()),
        "n_negative": int((r < 0).sum()),
    }
    AUDIT_LOG.append(entry)
    print(
        f"[DSR-AUDIT] n_obs={entry['n_obs']:3d} n_trials={entry['n_trials']:3d} "
        f"raw_sharpe={entry['raw_sharpe']:.4f} (mean={entry['mean_ret']:.6f}, std={entry['std_ret']:.6f}) "
        f"skew={entry['skew']:.3f} kurt={entry['kurt']:.3f} "
        f"wins={entry['n_positive']} losses={entry['n_negative']} "
        f"expected_max={entry['expected_max']:.4f} se={entry['sharpe_std_error']:.4f} "
        f"-> DSR={entry['result_dsr']:.6f}"
    )
    return result


ds_module.deflated_sharpe_from_returns = _instrumented

# ── Import the runner and its gate internals AFTER the patch ────────────────
import run_mes_trend_rv_filter_rank2 as runner  # noqa: E402
import backtest._gate_v2_trade_metrics as trade_metrics  # noqa: E402


def main():
    print("=" * 90)
    print("DSR END-TO-END AUDIT — MES RV-Filter Rank2 (real OOS trade data)")
    print("=" * 90)
    print()

    # Run the REAL WFO (baseline, no SOTA — matching the on-file verdict so
    # we are auditing the exact same computation that produced dsr=0.000525).
    verdict = runner.run_wfo(sota_hardening=False)

    print()
    print("=" * 90)
    print("AUDIT SUMMARY")
    print("=" * 90)
    if not AUDIT_LOG:
        print("No DSR calls logged — gate never reached?")
        return

    n_calls = len(AUDIT_LOG)
    # The final gate call is the one that matters (fixed-params + cost-sweep
    # intermediate runs also call DSR; the gate DSR is the last one per window set).
    final = AUDIT_LOG[-1]
    print(f"Total DSR calls in run: {n_calls}")
    print(f"Last (gate) call: n_obs={final['n_obs']} n_trials={final['n_trials']} "
          f"raw_sharpe={final['raw_sharpe']} -> DSR={final['result_dsr']}")
    print()
    print(f"Expected-max null at n_trials={final['n_trials']}: {final['expected_max']}")
    print(f"Observed raw Sharpe: {final['raw_sharpe']}")
    print(f"Gap to null: {final['expected_max'] - final['raw_sharpe']:.4f} Sharpe units")
    print()
    print("Conclusion check: if raw_sharpe < expected_max, the gate CANNOT pass this")
    print("strategy regardless of edge quality — the null bar exceeds the achievable")
    print("raw Sharpe for a trade-based (lumpy/binary) return series.")
    print()
    print(f"Actual verdict: {verdict.get('verdict')}")
    print(f"Gate DSR recorded: {verdict.get('gate_v2_metrics', {}).get('dsr')}")


if __name__ == "__main__":
    main()
