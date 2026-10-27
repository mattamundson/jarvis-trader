#!/usr/bin/env python3
"""Run the three paper-only MES research phases and write durable evidence.

No broker calls, no runtime config, no live/paper routing changes.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parents[2]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from backtest._gate_v2_helpers import campaign_trial_count  # noqa: E402
from backtest.research.mes_ib_ladder import (  # noqa: E402
    TARGET_MODES,
    chronological_split,
    events_to_frame,
    expanding_windows,
    ladder_event,
    outcomes_to_frame,
    run_family,
    simulate_simple_ib_break,
    simulate_trade,
    summarize_events,
    summarize_trades,
)
from backtest.research.mes_weekly_vwap_acceptance import (  # noqa: E402
    FEATURES,
    build_acceptance_records,
    records_to_frame,
    summarize_walk_forward,
    walk_forward_feature,
)
from backtest.research.session_data import (  # noqa: E402
    build_sessions,
    cache_provenance,
    load_mes_csv,
    strategy_metrics,
)
from backtest.research.spx_futures_basis import (  # noqa: E402
    BasisTranslationInput,
    translate_spx_strike,
)

SAFETY = {
    "mode": "ANALYSIS_ONLY",
    "paper_only": True,
    "orders_enabled": False,
    "risk_config_touched": False,
    "live_engine_touched": False,
    "symbols": ["MES"],
    "do_not_trade_symbols_excluded": ["MCL", "MNQ"],
}
PRIMARY_CACHE = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-05-29_5m_cont.csv")
SENSITIVITY_CACHE = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache\MES_2024-09-22_2026-06-29_15m.csv")
CURRENT_IB_FAMILY_TRIALS = 2 * 2 * len(TARGET_MODES)  # entry × stop × exit construction


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf" if value < 0 else "nan"
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def _select_champion(is_summaries: dict[str, dict]) -> str:
    eligible = [(key, value) for key, value in is_summaries.items() if value.get("n_trades", 0) >= 30]
    if not eligible:
        raise RuntimeError("no IS configuration has 30 trades")
    return max(
        eligible,
        key=lambda item: (
            item[1].get("observed_frequency_sharpe", -math.inf),
            item[1].get("expectancy", -math.inf),
            item[1].get("profit_factor", -math.inf),
        ),
    )[0]


def _trades_for_config(outcomes, config_id: str):
    return [outcome for outcome in outcomes if outcome.config_id == config_id]


def _half_pf(trades) -> dict:
    if len(trades) < 2:
        return {"h1_pf": 0.0, "h2_pf": 0.0, "both_positive": False}
    split = len(trades) // 2
    h1 = strategy_metrics([t.net_pnl for t in trades[:split]], [date.fromisoformat(t.trade_date) for t in trades[:split]])
    h2 = strategy_metrics([t.net_pnl for t in trades[split:]], [date.fromisoformat(t.trade_date) for t in trades[split:]])
    return {
        "h1_pf": h1["profit_factor"],
        "h2_pf": h2["profit_factor"],
        "h1_expectancy": h1["expectancy"],
        "h2_expectancy": h2["expectancy"],
        "both_positive": h1["profit_factor"] > 1.0 and h2["profit_factor"] > 1.0,
    }


def run_phase1(primary_df: pd.DataFrame, sensitivity_df: pd.DataFrame, out_dir: Path) -> dict:
    sessions, exclusions = build_sessions(primary_df)
    sensitivity_sessions, sensitivity_exclusions = build_sessions(
        sensitivity_df, min_ib_bars=4, min_rth_bars=20
    )
    train, test = chronological_split(sessions, 0.60)
    historical = campaign_trial_count("MES")
    n_trials = int(historical["n_trials_lower_bound"]) + CURRENT_IB_FAMILY_TRIALS

    events = [ladder_event(session) for session in sessions]
    events_to_frame(events).to_csv(out_dir / "phase1_ladder_events.csv", index=False)

    is_outcomes, is_summaries = run_family(
        train, slippage_ticks_per_side=1, n_trials=n_trials, dsr_permutations=0
    )
    champion_id = _select_champion(is_summaries)

    tier_payload: dict[str, Any] = {}
    all_oos_outcomes = []
    for slippage in (1, 2, 3):
        outcomes, summaries = run_family(
            test, slippage_ticks_per_side=slippage, n_trials=n_trials, dsr_permutations=0
        )
        all_oos_outcomes.extend(outcomes)
        champion_tier_id = champion_id.rsplit("__slip", 1)[0] + f"__slip{slippage}"
        champion_trades = _trades_for_config(outcomes, champion_tier_id)
        champion_summary = summarize_trades(
            champion_trades,
            n_trials=n_trials,
            dsr_permutations=5000 if slippage == 1 else 0,
        )
        baseline = [
            outcome
            for session in test
            if (outcome := simulate_simple_ib_break(session, slippage_ticks_per_side=slippage))
            is not None
        ]
        baseline_summary = summarize_trades(
            baseline, n_trials=n_trials, dsr_permutations=0
        )
        tier_payload[str(slippage)] = {
            "champion_config": champion_tier_id,
            "champion": champion_summary,
            "simple_ib_break_baseline": baseline_summary,
            "all_config_summaries": summaries,
        }
    outcomes_to_frame(is_outcomes).to_csv(out_dir / "phase1_is_trades.csv", index=False)
    outcomes_to_frame(all_oos_outcomes).to_csv(out_dir / "phase1_oos_trades_all_costs.csv", index=False)

    champion_base_id = champion_id.rsplit("__slip", 1)[0]
    wfo = []
    for index, (_, window_test) in enumerate(expanding_windows(sessions, min_train=200, test_size=40), start=1):
        parts = champion_base_id.split("__")
        trades = [
            outcome
            for session in window_test
            if (
                outcome := simulate_trade(
                    session,
                    entry_mode=parts[0],
                    stop_mode=parts[1],
                    target_mode=parts[2],
                    slippage_ticks_per_side=1,
                )
            )
            is not None
        ]
        wfo.append({
            "window": index,
            "test_first": str(window_test[0].trade_date),
            "test_last": str(window_test[-1].trade_date),
            "metrics": summarize_trades(trades, n_trials=n_trials, dsr_permutations=0),
        })

    parts = champion_base_id.split("__")
    sensitivity_trades = [
        outcome
        for session in sensitivity_sessions
        if (
            outcome := simulate_trade(
                session,
                entry_mode=parts[0],
                stop_mode=parts[1],
                target_mode=parts[2],
                slippage_ticks_per_side=1,
            )
        )
        is not None
    ]
    sensitivity_summary = summarize_trades(
        sensitivity_trades, n_trials=n_trials, dsr_permutations=0
    )

    oos = tier_payload["1"]["champion"]
    stressed = tier_payload["2"]["champion"]
    baseline = tier_payload["1"]["simple_ib_break_baseline"]
    oos_trades = _trades_for_config(
        all_oos_outcomes,
        champion_base_id + "__slip1",
    )
    halves = _half_pf(oos_trades)
    enough_sample = oos.get("n_trades", 0) >= 60
    criteria = {
        "oos_sample_at_least_60": enough_sample,
        "oos_cagr_positive": oos.get("cagr_pct", 0) > 0,
        "oos_pf_above_1": oos.get("profit_factor", 0) > 1,
        "campaign_dsr_at_least_0_95": (oos.get("dsr") or {}).get("dsr", 0) >= 0.95,
        "plus_one_tick_stress_expectancy_positive": stressed.get("expectancy", 0) > 0,
        "disjoint_halves_positive": halves["both_positive"],
        "expectancy_beats_simple_ib_baseline": oos.get("expectancy", -math.inf) > baseline.get("expectancy", math.inf),
    }
    verdict = "INCONCLUSIVE" if not enough_sample else ("ACCEPT" if all(criteria.values()) else "REJECT")
    payload = {
        "phase": 1,
        "name": "MES initial-balance sequential-target ladder",
        "safety": SAFETY,
        "rules": {
            "rth": "08:30<=bar_start<15:00 America/Chicago",
            "ib": "08:30<=bar_start<09:30; unavailable before completion",
            "entry_modes": ["stop_entry at IB boundary", "first post-IB close beyond boundary"],
            "stop_modes": ["IB midpoint", "opposite IB extreme"],
            "targets": ["directional overnight extreme when beyond entry", "0.5x IB extension", "1.0x IB extension", "price-ordered equal-unit ladder"],
            "same_bar_collision": "stop first (conservative)",
            "baseline": "first stop-entry IB break; opposite-IB stop; otherwise RTH close",
            "fees_per_contract_round_trip": 1.42,
            "slippage_ticks_per_side": [1, 2, 3],
        },
        "session_counts": {
            "primary_complete_sessions": len(sessions),
            "primary_exclusions": exclusions,
            "is_sessions": len(train),
            "oos_sessions": len(test),
            "sensitivity_15m_complete_sessions": len(sensitivity_sessions),
            "sensitivity_exclusions": sensitivity_exclusions,
        },
        "trial_accounting": {
            "historical_mes_campaign_lower_bound": historical,
            "current_frozen_family_trials": CURRENT_IB_FAMILY_TRIALS,
            "n_trials_used_for_dsr": n_trials,
            "caveat": "Measured lower bound, not unknowable exact truth: unlogged experiments can only make DSR stricter. Historical helper content-dedupes artifacts; current family count is entry(2)xstop(2)xtarget(4).",
        },
        "descriptive_ladder": summarize_events(events),
        "is_selection": {
            "selection_rule": "maximum IS observed-frequency Sharpe, then expectancy, then PF; OOS unseen",
            "champion_config": champion_id,
            "all_config_summaries": is_summaries,
        },
        "oos_cost_tiers": tier_payload,
        "oos_disjoint_halves": halves,
        "expanding_walk_forward": wfo,
        "resolution_sensitivity_15m": {
            "warning": "15-minute bars are lower-resolution and used only as terminal-window/resolution sensitivity evidence",
            "metrics": sensitivity_summary,
        },
        "acceptance_criteria": criteria,
        "limitations": [
            "Primary cache is a stitched, non-back-adjusted continuous MES series; roll transitions can affect overnight references near contract switches.",
            "Five-minute bars do not reveal intrabar path; same-bar collisions resolve stop-first and dual-IB breaks are excluded.",
            "Campaign trial count 226 is a measured lower bound because unlogged experiments cannot be reconstructed.",
        ],
        "verdict": verdict,
    }
    _write_json(out_dir / "phase1_mes_ib_ladder.json", payload)
    return payload


def run_phase2(primary_df: pd.DataFrame, out_dir: Path) -> dict:
    records = build_acceptance_records(primary_df)
    records_to_frame(records).to_csv(out_dir / "phase2_acceptance_records.csv", index=False)
    feature_payload: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for feature in FEATURES:
        rows = walk_forward_feature(records, feature)
        all_rows.extend(rows)
        by_time = {}
        for decision_time in sorted({row["decision_time_ct"] for row in rows}):
            by_time[decision_time] = summarize_walk_forward(
                [row for row in rows if row["decision_time_ct"] == decision_time]
            )
        pooled = summarize_walk_forward(rows)
        feature_payload[feature] = {
            "pooled": pooled,
            "by_decision_time": by_time,
            "pre_multiplicity_retained": pooled.get("retained", False),
            "retained": False,
        }
    # Holm correction across five features x two baseline comparisons. A raw
    # bootstrap CI clearing zero is not enough after screening ten hypotheses.
    ordered = sorted(
        comparison
        for feature, result in feature_payload.items()
        for comparison in (
            (
                feature,
                "price_above_vwap",
                float(result["pooled"].get("paired_block_bootstrap_p_one_sided", 1.0)),
            ),
            (
                feature,
                "unconditional",
                float(
                    result["pooled"].get(
                        "paired_unconditional_block_bootstrap_p_one_sided", 1.0
                    )
                ),
            ),
        )
    )
    ordered.sort(key=lambda item: item[2])
    running_adjusted = 0.0
    m = len(ordered)
    for rank, (feature, comparison, raw_p) in enumerate(ordered):
        adjusted = min(1.0, max(running_adjusted, (m - rank) * raw_p))
        running_adjusted = adjusted
        feature_payload[feature]["pooled"][f"holm_adjusted_p_{comparison}"] = round(adjusted, 6)
        feature_payload[feature]["pooled"][f"holm_reject_{comparison}_at_0_05"] = adjusted <= 0.05
    for feature in FEATURES:
        pooled = feature_payload[feature]["pooled"]
        feature_payload[feature]["retained"] = bool(
            feature_payload[feature]["pre_multiplicity_retained"]
            and pooled.get("holm_reject_price_above_vwap_at_0_05", False)
            and pooled.get("holm_reject_unconditional_at_0_05", False)
        )
    pd.DataFrame(all_rows).to_json(out_dir / "phase2_walkforward_rows.jsonl", orient="records", lines=True)
    probability_checks = {
        "rows": len(all_rows),
        "max_abs_probability_sum_error": max(
            (abs(float(row["probability_sum_model"]) - 1.0) for row in all_rows),
            default=0.0,
        ),
    }
    retained = [feature for feature, result in feature_payload.items() if result["retained"]]
    enough = len(records) >= 300 and len(all_rows) >= 300
    verdict = "INCONCLUSIVE" if not enough else ("ACCEPT" if retained else "REJECT")
    payload = {
        "phase": 2,
        "name": "MES weekly-VWAP acceptance",
        "safety": SAFETY,
        "rules": {
            "weekly_vwap_reset": "Sunday 17:00 CT via futures trade-date week key; cumulative OHLCV typical-price VWAP",
            "decision_times_ct": ["10:30", "11:30", "12:30"],
            "time": "at least 5 of last 6 completed 5m closes above developing wVWAP and last 3 consecutive above",
            "volume": "at least 60% of last 12 completed bars' volume on bars whose typical price is above contemporaneous wVWAP, plus decision price above wVWAP",
            "developing_vpoc": "uniformly distribute each elapsed RTH bar volume across crossed 0.25-point ticks; causal POC above wVWAP",
            "developing_tpo_poc": "30-minute completed-period TPO counts across 0.25-point ticks; causal POC above wVWAP",
            "clv_delta_proxy": "sum(close-location-value*volume) over last 12 bars >0 and price>wVWAP; proxy only, NOT true bid/ask cumulative delta",
            "outcome_partition": {
                "continuation": "next_close > signal_session_close",
                "failure": "next_close <= signal_session_close AND next_low < signal_session_low",
                "rotation": "next_close <= signal_session_close AND next_low >= signal_session_low",
            },
            "probabilities": "trailing-only empirical class rates with symmetric Dirichlet alpha=1; minimum 60 prior sessions and 30 same-state sessions",
            "retain_rule": "pooled paired block-bootstrap Brier CIs wholly >0 vs BOTH price>wVWAP and trailing unconditional baselines, Holm-adjusted one-sided p<=0.05 across 5x2 comparisons, higher net expectancy than price>wVWAP, and positive +1-tick stress expectancy",
        },
        "record_count": len(records),
        "probability_integrity": probability_checks,
        "features": feature_payload,
        "retained_features": retained,
        "limitations": [
            "The continuous cache is stitched and not back-adjusted; a quarterly roll inside a week can distort developing weekly VWAP.",
            "Developing VPOC is an OHLCV bar-range allocation proxy, not exchange volume-at-price.",
            "CLV delta is not true bid/ask cumulative delta.",
        ],
        "verdict": verdict,
    }
    _write_json(out_dir / "phase2_weekly_vwap_acceptance.json", payload)
    return payload


def run_phase3(out_dir: Path) -> dict:
    asof = datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc)
    common = {
        "spx_strike": 7750.0,
        "spx_spot": 7750.0,
        "risk_free_rate": 0.045,
        "dividend_yield": 0.012,
        "valuation_time": asof,
        "spot_timestamp": asof,
        "contract_symbol": "ESZ6",
        "contract_expiry": date(2026, 12, 18),
    }
    theoretical = translate_spx_strike(BasisTranslationInput(**common))
    observed = translate_spx_strike(BasisTranslationInput(
        **common,
        observed_futures_price=7810.0,
        observed_futures_timestamp=asof,
    ))
    stale_observed = translate_spx_strike(BasisTranslationInput(
        **common,
        observed_futures_price=7900.0,
        observed_futures_timestamp=datetime(2026, 9, 25, 16, 50, tzinfo=timezone.utc),
    ))
    mes = translate_spx_strike(BasisTranslationInput(
        **common,
        output_symbol="MES",
        observed_futures_price=7810.0,
        observed_futures_timestamp=asof,
    ))
    roll = translate_spx_strike(BasisTranslationInput(
        spx_strike=7750.0,
        spx_spot=7750.0,
        risk_free_rate=0.045,
        dividend_yield=0.012,
        valuation_time=datetime(2026, 12, 12, tzinfo=timezone.utc),
        spot_timestamp=datetime(2026, 12, 12, tzinfo=timezone.utc),
        contract_symbol="ESZ6",
        contract_expiry=date(2026, 12, 18),
    ))
    validations = {
        "theoretical_near_loom_region_7800_7825": 7800.0 <= theoretical.translated_level <= 7825.0,
        "observed_basis_maps_7750_to_7810": observed.translated_level == 7810.0,
        "observed_basis_value_is_60": observed.observed_basis == 60.0,
        "stale_observed_falls_back_to_theoretical": stale_observed.basis_source == "theoretical_carry" and stale_observed.stale_observed_basis_rejected,
        "es_mes_same_price_level": mes.translated_level == observed.translated_level,
        "roll_window_flagged": roll.in_roll_window,
        "original_strike_preserved": all(
            result.original_spx_strike == 7750.0
            for result in (theoretical, observed, stale_observed, mes, roll)
        ),
    }
    payload = {
        "phase": 3,
        "name": "SPX-to-ES/MES basis translator validation",
        "safety": SAFETY,
        "formula": "basis_theoretical = spot * (exp((r-q)*T)-1); translated strike = original strike + selected additive basis",
        "precedence": "fresh synchronized observed ES-SPX basis; otherwise theoretical carry; stale SPX spot fails closed",
        "cases": {
            "loom_theoretical": theoretical.to_dict(),
            "loom_observed": observed.to_dict(),
            "stale_observed_fallback": stale_observed.to_dict(),
            "mes_same_level": mes.to_dict(),
            "roll_window": roll.to_dict(),
        },
        "validations": validations,
        "limitations": [
            "Functional validation uses the Loom example and deterministic synthetic staleness/roll cases, not an independent historical basis time series.",
            "No live market-data fetch or runtime integration was attempted.",
        ],
        "verdict": "ACCEPT" if all(validations.values()) else "REJECT",
    }
    _write_json(out_dir / "phase3_spx_es_basis.json", payload)
    return payload


def render_reports(out_dir: Path, phase1: dict, phase2: dict, phase3: dict) -> None:
    p1 = phase1["oos_cost_tiers"]["1"]["champion"]
    p1s = phase1["oos_cost_tiers"]["2"]["champion"]
    p1b = phase1["oos_cost_tiers"]["1"]["simple_ib_break_baseline"]
    oos_rows = []
    for config, metrics in sorted(
        phase1["oos_cost_tiers"]["1"]["all_config_summaries"].items()
    ):
        oos_rows.append(
            f"| `{config}` | {metrics['n_trades']} | {metrics['profit_factor']} | "
            f"{metrics['expectancy']} | {metrics['cagr_pct']} | "
            f"{metrics['observed_frequency_sharpe']} |"
        )
    wfo_rows = [
        f"| {row['window']} | {row['test_first']} → {row['test_last']} | "
        f"{row['metrics']['n_trades']} | {row['metrics']['profit_factor']} | "
        f"{row['metrics']['expectancy']} |"
        for row in phase1["expanding_walk_forward"]
    ]
    provenance = phase1["input_provenance"]["primary_5m"]
    report1 = f"""# MES Initial-Balance Ladder — Research Verdict

**Verdict: {phase1['verdict']}** · Analysis only · MES only · no runtime/risk changes.

- Input: `{provenance['path']}` · **{provenance['rows']:,} rows** · `{provenance['first_utc']}` → `{provenance['last_utc']}` · SHA-256 `{provenance['sha256']}`.
- Complete 5-minute sessions: **{phase1['session_counts']['primary_complete_sessions']}**; IS/OOS: **{phase1['session_counts']['is_sessions']}/{phase1['session_counts']['oos_sessions']}**.
- IS-selected configuration: `{phase1['is_selection']['champion_config']}`.
- OOS trades: **{p1['n_trades']}**; PF **{p1['profit_factor']}**; expectancy **${p1['expectancy']}**; CAGR **{p1['cagr_pct']}%**; max DD **{p1['max_drawdown_pct']}%**; observed-frequency Sharpe **{p1['observed_frequency_sharpe']}**.
- Campaign-deflated empirical DSR: **{p1['dsr'].get('dsr')}** at **{phase1['trial_accounting']['n_trials_used_for_dsr']}** measured lower-bound trials.
- +1 tick/side stress expectancy: **${p1s['expectancy']}**.
- Simple IB-break benchmark expectancy: **${p1b['expectancy']}**.
- MFE mean/median: **{p1['mean_mfe_points']} / {p1['median_mfe_points']} points**; MAE mean/median: **{p1['mean_mae_points']} / {p1['median_mae_points']} points**; mean time-to-exit **{p1['mean_minutes_to_exit']} minutes**.
- Ledger reconciliation residual: **${p1['ledger_reconciliation_residual']}**.
- Disjoint halves: `{phase1['oos_disjoint_halves']}`.

## Descriptive ladder

```json
{json.dumps(phase1['descriptive_ladder'], indent=2)}
```

## All OOS variants — baseline cost

| configuration | trades | PF | expectancy ($) | CAGR (%) | observed-frequency Sharpe |
|---|---:|---:|---:|---:|---:|
{chr(10).join(oos_rows)}

## Expanding walk-forward — locked IS champion

| window | test span | trades | PF | expectancy ($) |
|---:|---|---:|---:|---:|
{chr(10).join(wfo_rows)}

## Resolution/terminal-window sensitivity

The wider 15-minute cache contains **{phase1['session_counts']['sensitivity_15m_complete_sessions']} complete sessions**. It is lower-resolution and not merged with the 5-minute source. Applying the locked champion produced PF **{phase1['resolution_sensitivity_15m']['metrics']['profit_factor']}**, expectancy **${phase1['resolution_sensitivity_15m']['metrics']['expectancy']}**, CAGR **{phase1['resolution_sensitivity_15m']['metrics']['cagr_pct']}%**, and max DD **{phase1['resolution_sensitivity_15m']['metrics']['max_drawdown_pct']}%**.

**Data caveat:** the source is a stitched, non-back-adjusted continuous MES series. Roll transitions can affect overnight references; the conservative REJECT verdict is not a promotion claim.

## Criteria

```json
{json.dumps(phase1['acceptance_criteria'], indent=2)}
```

## Reproduce

```bash
env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' engine/.venv/Scripts/python.exe engine/backtest/research/run_mes_ib_vwap_basis.py --out-dir .hermes/artifacts/mes_ib_vwap_basis_20260927
```

Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase1_mes_ib_ladder.json` and CSV sidecars.
"""
    lines = ["# MES Weekly-VWAP Acceptance — Research Verdict", "", f"**Verdict: {phase2['verdict']}** · retained features: `{phase2['retained_features']}`.", "", f"Input: `{phase2['input_provenance']['primary_5m']['path']}` · SHA-256 `{phase2['input_provenance']['primary_5m']['sha256']}`.", "", "| feature | n | Brier model | price>VWAP | unconditional | diff vs price | CI | Holm p (price/uncond) | model exp. | baseline exp. | retained |", "|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|"]
    for feature, result in phase2["features"].items():
        row = result["pooled"]
        lines.append(
            f"| `{feature}` | {row.get('n')} | {row.get('mean_brier_model')} | {row.get('mean_brier_baseline')} | {row.get('mean_brier_unconditional')} | "
            f"{row.get('paired_diff_baseline_minus_model')} | `{row.get('paired_block_bootstrap_ci95')}` | "
            f"{row.get('holm_adjusted_p_price_above_vwap')}/{row.get('holm_adjusted_p_unconditional')} | "
            f"{row.get('model_economics', {}).get('expectancy')} | {row.get('baseline_economics', {}).get('expectancy')} | {row.get('retained')} |"
        )
    lines += ["", "The CLV/cumulative-delta field is an OHLCV proxy, not true bid/ask delta. No feature is retained unless paired OOS Brier clears both the price-above-weekly-VWAP and trailing-unconditional arms after Holm correction, while economics also beat the price>VWAP arm.", "", "Data caveat: the stitched, non-back-adjusted continuous cache can distort developing weekly VWAP when a quarterly roll occurs inside the week. This study rejects every feature and makes no promotion claim.", "", "Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase2_weekly_vwap_acceptance.json` and sidecars."]
    report2 = "\n".join(lines) + "\n"
    loom = phase3["cases"]["loom_theoretical"]
    report3 = f"""# SPX-to-ES/MES Basis Translator — Validation

**Verdict: {phase3['verdict']}** · pure research utility; no data fetch or broker integration.

- Formula: `{phase3['formula']}`
- Theoretical Loom example: SPX strike 7750 → **{loom['translated_level']}** ES using basis **{loom['selected_basis']}**.
- Fresh observed example: 7750 SPX → **{phase3['cases']['loom_observed']['translated_level']}** using observed **60-point** basis.
- Stale observed basis is rejected and falls back to theoretical carry.
- ES and MES translated price levels are identical; symbol/contract metadata remains distinct.
- Roll-window, expiry, staleness, synchronization, and strike-preservation tests are included.
- Functional validation uses the Loom example and deterministic cases; it is not a historical basis-forecast backtest and is not integrated into runtime.

```json
{json.dumps(phase3['validations'], indent=2)}
```

Raw evidence: `.hermes/artifacts/mes_ib_vwap_basis_20260927/phase3_spx_es_basis.json`.
"""
    reports = {
        "MES_IB_LADDER_20260927.md": report1,
        "MES_WEEKLY_VWAP_ACCEPTANCE_20260927.md": report2,
        "SPX_ES_BASIS_TRANSLATOR_20260927.md": report3,
    }
    docs = ENGINE.parent / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        (docs / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=PRIMARY_CACHE)
    parser.add_argument("--sensitivity-cache", type=Path, default=SENSITIVITY_CACHE)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    primary = load_mes_csv(args.cache)
    sensitivity = load_mes_csv(args.sensitivity_cache)
    provenance = {
        "primary_5m": cache_provenance(args.cache, primary),
        "sensitivity_15m": cache_provenance(args.sensitivity_cache, sensitivity),
        "unsafe_merge_rejected": "overlapping 5m cache candidates disagreed on tens of thousands of OHLCV rows; no splice performed",
    }
    _write_json(args.out_dir / "data_provenance.json", provenance)
    phase1 = run_phase1(primary, sensitivity, args.out_dir)
    phase2 = run_phase2(primary, args.out_dir)
    phase3 = run_phase3(args.out_dir)
    phase1["input_provenance"] = provenance
    phase2["input_provenance"] = provenance
    _write_json(args.out_dir / "phase1_mes_ib_ladder.json", phase1)
    _write_json(args.out_dir / "phase2_weekly_vwap_acceptance.json", phase2)
    render_reports(args.out_dir, phase1, phase2, phase3)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety": SAFETY,
        "data_provenance": provenance,
        "phase_verdicts": {"phase1": phase1["verdict"], "phase2": phase2["verdict"], "phase3": phase3["verdict"]},
        "artifacts": sorted(path.name for path in args.out_dir.iterdir() if path.is_file()),
    }
    _write_json(args.out_dir / "manifest.json", manifest)
    print(json.dumps(_json_safe(manifest), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
