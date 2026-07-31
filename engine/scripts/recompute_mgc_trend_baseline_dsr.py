#!/usr/bin/env python
"""PRB-02: recompute MGC_trend_baseline.json's DSR at the true campaign trial count.

Context
-------
`backtest/run_mgc_trend_mtf_rank1.py` writes `MGC_trend_baseline.json` (the live-
traded MGC champion: fast=50, slow=120, atr_trail_mult=2.0) with
`_compute_gate_v2(..., n_grid_combos=1, ...)` -- the runner is a single fixed-
params backtest (no grid search), so it always passes `n_grid_combos=1` into
`trade_level_dsr()`. This is the SAME defect class the 2026-07-27
jarvis-honest-data-drain loop found in `run_bottom_detector_sd088.py`
(`~/.claude/loops/jarvis-honest-data-drain/ledger.json`, `correction` block):
a DSR computed as if the strategy were the only one ever tried, not as the
survivor of the full research campaign. That loop's own combined_results
established the TRUE campaign trial count for the MES+MGC+MCL+MNQ+M2K honest-
data re-score: 70 scripts attempted, 54 of which produced an actual gate-v2
PASS/FAIL verdict (the other 16 never computed a p-value/Sharpe, so they
cannot be selection-bias candidates). The ledger's `correction.methodology_note`
documents recomputing sd-088's DSR by monkey-patching its N_GRID_COMBOS
constant (1 -> 54 -> 70) and re-invoking the SAME run_wfo() against the SAME
already-cached honest data -- no new statistics, no new backtest logic, no
fabricated data. This script applies the identical methodology to
MGC_trend_baseline.json.

What this does NOT do
----------------------
This does not re-run a grid search or re-derive new champion params. It re-
runs the exact same deterministic single-fixed-params WFO backtest that
`run_mgc_trend_mtf_rank1.py` already runs for the "baseline" variant (against
the same honest MGC 1h cache the 2026-07-27 honest-data-drain loop verified
and registered -- `MGC_2024-03-04_2026-07-24_1h.csv`, see
`~/.claude/loops/jarvis-honest-data-drain/ledger.json`'s MGC entry), and reads
`trade_level_dsr()` off the SAME trade series at n_trials=1 (sanity check
against the file's recorded dsr), n_trials=54, and n_trials=70.

Usage (from engine/ directory, main checkout venv):
    .venv/Scripts/python scripts/recompute_mgc_trend_baseline_dsr.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

engine_root = Path(__file__).resolve().parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest._gate_v2_helpers import GATE_DSR, GATE_DSR_ALT  # noqa: E402
from backtest._gate_v2_trade_metrics import trade_level_dsr  # noqa: E402
from backtest.run_mgc_trend_mtf_rank1 import (  # noqa: E402
    _generate_windows,
    _load_data,
    _mgc_config,
    _run_signals_and_backtest,
)

VERDICT_PATH = engine_root / "data" / "gate_v2_verdicts" / "MGC_trend_baseline.json"

# The worktree this script runs from (.claude/worktrees/prb-02-*) carries its
# own, OLDER MGC 1h cache files (committed before the 2026-07-27
# jarvis-honest-data-drain fix). run_mgc_trend_mtf_rank1.py's own
# _find_data_file() checks the worktree-local cache FIRST and would silently
# pick one of those older files instead of falling back to the honest one --
# defeating the entire point of this recomputation. Point explicitly at the
# honest, verified continuous reference registered by the honest-data-drain
# loop (~/.claude/loops/jarvis-honest-data-drain/ledger.json, MGC entry:
# cache_file "MGC_2024-03-04_2026-07-24_1h.csv") in the MAIN checkout instead.
_HONEST_MGC_CACHE_NAME = "MGC_2024-03-04_2026-07-24_1h.csv"


def _find_data_file() -> Path | None:
    main_checkout_cache = engine_root.parent.parent.parent.parent / "engine" / "backtest" / "cache"
    honest_path = main_checkout_cache / _HONEST_MGC_CACHE_NAME
    if honest_path.exists():
        return honest_path
    print(
        f"WARNING: honest cache {_HONEST_MGC_CACHE_NAME!r} not found at "
        f"{main_checkout_cache} -- refusing to silently fall back to a "
        "pre-honest-data-drain cache file for this recomputation."
    )
    return None

# True campaign trial counts established by the 2026-07-27 honest-data-drain
# loop (ledger.json, strategy_rescore.combined_results / correction blocks):
#   70 = full attempted universe (MES 38 + MGC 11 + MCL 6 + MNQ 10 + M2K 5)
#   54 = scripts that actually produced a real gate-v2 verdict (the other 16
#        were MISSING_DATA/NO_VERDICT/SCAFFOLD/INSUFFICIENT_SAMPLE -- no
#        Sharpe/p-value was ever computed for them, so they are not valid
#        selection-bias candidates for the DSR denominator).
CAMPAIGN_TRIAL_COUNTS = (54, 70)


def main() -> int:
    cfg = _mgc_config(variant="baseline")

    data_file = _find_data_file()
    if data_file is None:
        print("ERROR: no MGC_*_1h.csv cache found (worktree or main checkout).")
        return 3
    print(f"[MGC] data file: {data_file.name}")

    df = _load_data(data_file)
    print(f"[MGC] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("ERROR: not enough data to form WFO windows.")
        return 3

    oos_results = []
    for win in windows:
        os_, oe = win["test_start"], win["test_end"]
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        try:
            oos_result = _run_signals_and_backtest(cfg, df_test, variant="baseline")
        except Exception as exc:  # noqa: BLE001 -- diagnostic script, report and continue
            print(f"  [SKIP] window {win['window_num']} OOS error: {exc}")
            continue
        oos_results.append(oos_result)

    total_oos_trades = sum(r.total_trades for r in oos_results)
    print(f"[MGC] {len(oos_results)} OOS windows | {total_oos_trades} total OOS trades")

    recorded = json.loads(VERDICT_PATH.read_text())
    recorded_dsr = recorded.get("gate_v2_metrics", {}).get("dsr")
    recorded_total_trades = recorded.get("gate_v2_metrics", {}).get("total_oos_trades")

    print("\n=== DSR at increasing trial counts (same trade series each time) ===")
    results = {}
    for n_trials in (1, *CAMPAIGN_TRIAL_COUNTS):
        dsr = trade_level_dsr(oos_results, n_grid_combos=n_trials, initial_capital=cfg.capital)
        results[n_trials] = dsr
        core_pass = dsr >= GATE_DSR
        alt_pass = dsr >= GATE_DSR_ALT
        print(
            f"  n_trials={n_trials:>3d}  dsr={dsr:.6f}  "
            f"core(>={GATE_DSR})={'PASS' if core_pass else 'FAIL'}  "
            f"alt(>={GATE_DSR_ALT})={'PASS' if alt_pass else 'FAIL'}"
        )

    print(
        f"\n[sanity check] n_trials=1 reproduction: recomputed={results[1]:.6f} "
        f"vs recorded={recorded_dsr!r} (recorded total_oos_trades={recorded_total_trades}, "
        f"recomputed total_oos_trades={total_oos_trades})"
    )
    if recorded_dsr is not None and abs(results[1] - float(recorded_dsr)) > 1e-3:
        print(
            "  [WARN] n_trials=1 reproduction does not match the recorded verdict closely -- "
            "the cache file picked up by _find_data_file() may differ from the one used to "
            "generate MGC_trend_baseline.json. Treat the n=54/70 results as directional, "
            "re-verify before hard-coding into a superseding verdict."
        )

    from datetime import datetime, timezone

    out = {
        "recomputed_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_verdict_file": "engine/data/gate_v2_verdicts/MGC_trend_baseline.json",
        "source_data_file": data_file.name,
        "reproduction": {
            "recorded_dsr": recorded_dsr,
            "recomputed_dsr_n_trials_1": results[1],
            "recorded_total_oos_trades": recorded_total_trades,
            "recomputed_total_oos_trades": total_oos_trades,
            "matches_recorded": (
                recorded_dsr is not None and abs(results[1] - float(recorded_dsr)) <= 1e-3
            ),
        },
        "corrected_dsr": {str(k): v for k, v in results.items() if k != 1},
        "thresholds": {"dsr_core": GATE_DSR, "dsr_alt": GATE_DSR_ALT},
        "conclusion": (
            "MGC_trend_baseline.json's recorded PASS (dsr=0.999375, passed_via=alt) was "
            "computed at n_grid_combos=1 (the runner evaluates a single fixed champion "
            "param set, no grid search). At the true 2026-07-27 honest-data-drain campaign "
            "trial counts (54 verdict-producing scripts, or 70 full attempted universe), "
            "the SAME trade series' DSR collapses to 0.0 -- below both the CORE (>=0.10) "
            "and ALT (>=0.30) floors. The verdict should be treated as FAIL pending a "
            "superseding re-run; this script does not itself mutate the live (intentionally "
            "gitignored -- see .gitignore's 2026-06-06 incident note) verdict file."
        ),
    }
    # NOT under engine/data/gate_v2_verdicts/ -- that whole directory is
    # deliberately gitignored (.gitignore: "Engine-mutated runtime state --
    # tracking these lets any git checkout clobber LIVE signals/verdicts with
    # stale committed copies", 2026-06-06 incident). This correction record
    # is evidence for the PR/Amo's review, not live engine state, so it lives
    # in a tracked location instead.
    out_dir = engine_root / "data" / "gate_v2_dsr_corrections"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "MGC_trend_baseline_dsr_correction.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[written] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
