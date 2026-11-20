#!/usr/bin/env python3
"""Independent readback/reconciliation for MES IB/VWAP/basis evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


def _pf(values: pd.Series) -> float:
    wins = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return wins / losses if losses else (math.inf if wins else 0.0)


def _sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".csv", ".json", ".jsonl", ".md", ".py", ".txt"}:
        # Git may materialize text as CRLF on Windows even though the committed
        # blob is LF. Canonical text hashes survive clean cross-platform checkouts.
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify(out_dir: Path) -> dict:
    p1 = json.loads((out_dir / "phase1_mes_ib_ladder.json").read_text(encoding="utf-8"))
    p2 = json.loads((out_dir / "phase2_weekly_vwap_acceptance.json").read_text(encoding="utf-8"))
    p3 = json.loads((out_dir / "phase3_spx_es_basis.json").read_text(encoding="utf-8"))

    champion_id = p1["oos_cost_tiers"]["1"]["champion_config"]
    trades = pd.read_csv(out_dir / "phase1_oos_trades_all_costs.csv")
    champion = trades[trades["config_id"] == champion_id]
    expected = p1["oos_cost_tiers"]["1"]["champion"]
    phase1 = {
        "champion_id": champion_id,
        "row_count_raw": int(len(champion)),
        "row_count_reported": int(expected["n_trades"]),
        "net_pnl_raw": round(float(champion["net_pnl"].sum()), 6),
        "net_pnl_reported": float(expected["net_pnl"]),
        "profit_factor_raw": round(_pf(champion["net_pnl"]), 6),
        "profit_factor_reported": float(expected["profit_factor"]),
        "max_abs_trade_ledger_residual": float(champion["ledger_reconciliation_residual"].abs().max()),
        "aggregate_cost_identity_residual": round(float(
            champion["net_pnl"].sum()
            - (champion["gross_pnl"].sum() - champion["fees"].sum() - champion["slippage_cost"].sum())
        ), 12),
    }
    phase1["verified"] = bool(
        phase1["row_count_raw"] == phase1["row_count_reported"]
        and abs(phase1["net_pnl_raw"] - phase1["net_pnl_reported"]) < 1e-6
        and abs(phase1["profit_factor_raw"] - phase1["profit_factor_reported"]) < 1e-6
        and phase1["max_abs_trade_ledger_residual"] == 0.0
        and phase1["aggregate_cost_identity_residual"] == 0.0
    )

    wf = pd.read_json(out_dir / "phase2_walkforward_rows.jsonl", lines=True)
    volume = wf[wf["feature"] == "volume"].copy()
    reported = p2["features"]["volume"]["pooled"]
    by_date = {}
    for signal_date, group in volume.groupby("signal_date"):
        accepted = group[group["feature_state"]].sort_values("decision_time_ct")
        if not accepted.empty:
            row = accepted.iloc[0]
            by_date[str(signal_date)] = (float(row["next_close"]) - float(row["session_close"])) * 5.0 - 3.92
    probability_errors = [abs(sum(probs.values()) - 1.0) for probs in volume["p_model"]]
    phase2 = {
        "rows_raw": int(len(volume)),
        "rows_reported": int(reported["n"]),
        "mean_brier_model_raw": round(float(volume["brier_model"].mean()), 6),
        "mean_brier_model_reported": float(reported["mean_brier_model"]),
        "mean_brier_baseline_raw": round(float(volume["brier_baseline"].mean()), 6),
        "mean_brier_baseline_reported": float(reported["mean_brier_baseline"]),
        "paired_diff_raw": round(float((volume["brier_baseline"] - volume["brier_model"]).mean()), 6),
        "paired_diff_reported": float(reported["paired_diff_baseline_minus_model"]),
        "earliest_signal_trade_count_raw": len(by_date),
        "earliest_signal_trade_count_reported": int(reported["model_economics"]["n_trades"]),
        "expectancy_raw": round(sum(by_date.values()) / len(by_date), 6),
        "expectancy_reported": float(reported["model_economics"]["expectancy"]),
        "max_probability_sum_error": max(probability_errors),
        "holm_adjusted_p_price_above_vwap": float(
            reported["holm_adjusted_p_price_above_vwap"]
        ),
        "holm_adjusted_p_unconditional": float(
            reported["holm_adjusted_p_unconditional"]
        ),
        "retained": bool(p2["features"]["volume"]["retained"]),
    }
    phase2["verified"] = bool(
        phase2["rows_raw"] == phase2["rows_reported"]
        and phase2["mean_brier_model_raw"] == phase2["mean_brier_model_reported"]
        and phase2["mean_brier_baseline_raw"] == phase2["mean_brier_baseline_reported"]
        and phase2["paired_diff_raw"] == phase2["paired_diff_reported"]
        and phase2["earliest_signal_trade_count_raw"] == phase2["earliest_signal_trade_count_reported"]
        and phase2["expectancy_raw"] == phase2["expectancy_reported"]
        and phase2["max_probability_sum_error"] < 1e-9
    )

    loom = p3["cases"]["loom_theoretical"]
    theoretical = 7750.0 * math.exp((0.045 - 0.012) * float(loom["year_fraction"]))
    phase3 = {
        "theoretical_recomputed": round(theoretical, 8),
        "theoretical_reported": float(loom["theoretical_futures_price_at_spot"]),
        "translated_level_reported": float(loom["translated_level"]),
        "all_validation_flags_true": all(p3["validations"].values()),
    }
    phase3["verified"] = bool(
        abs(phase3["theoretical_recomputed"] - phase3["theoretical_reported"]) < 1e-8
        and phase3["all_validation_flags_true"]
    )

    files = sorted(
        path
        for path in out_dir.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and path.suffix.lower() != ".log"
    )
    payload = {
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
        "all_verified": phase1["verified"] and phase2["verified"] and phase3["verified"],
        "artifact_hashes": {path.name: _sha(path) for path in files},
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    payload = verify(args.out_dir)
    (args.out_dir / "artifact_hashes.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
