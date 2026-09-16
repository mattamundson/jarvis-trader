from __future__ import annotations

from morning_alpha.research.statistical_validation import StatisticalValidationBundle


def _fmt(value: float | None, digits: int = 6) -> str:
    return "unavailable" if value is None else f"{value:.{digits}f}"


def _fmt_curve(values: dict[object, float]) -> str:
    if not values:
        return "unavailable"
    return ", ".join(f"{key}={_fmt(value)}" for key, value in values.items())


def render_statistical_validation_report(bundle: StatisticalValidationBundle) -> str:
    iid_perm = bundle.permutation
    date_perm = bundle.date_cluster_permutation
    placebo = bundle.placebo
    iid_boot = bundle.iid_bootstrap
    date_boot = bundle.date_cluster_bootstrap
    sector_boot = bundle.sector_cluster_bootstrap
    concentration = bundle.concentration
    execution = bundle.execution_stress
    reasons = ", ".join(bundle.reasons) if bundle.reasons else "none"

    return "\n".join(
        [
            "STATISTICAL EVIDENCE IDENTITY",
            f"bundle_id: {bundle.bundle_id}",
            f"population_identity: {bundle.candidate_population_identity}",
            f"data_manifest_hash: {bundle.data_manifest_hash}",
            f"control_version: {bundle.control_version}",
            "",
            "SAMPLE STRUCTURE",
            f"observations: {bundle.n}",
            f"date_cluster_count: {bundle.date_cluster_count}",
            f"sector_cluster_count: {bundle.sector_cluster_count}",
            f"min_observations: {bundle.spec.min_observations}",
            f"min_date_clusters: {bundle.spec.min_date_clusters}",
            f"min_sector_clusters: {bundle.spec.min_sector_clusters}",
            "",
            "DATE-CLUSTER INFERENCE",
            f"date_cluster_mean_edge: {_fmt(date_perm.observed_mean_edge if date_perm else None)}",
            f"date_cluster_one_sided_p: {_fmt(date_perm.one_sided_p if date_perm else None)}",
            f"date_cluster_two_sided_p: {_fmt(date_perm.two_sided_p if date_perm else None)}",
            f"date_cluster_ci: [{_fmt(date_boot.lower if date_boot else None)}, {_fmt(date_boot.upper if date_boot else None)}]",
            f"date_fraction_non_positive: {_fmt(date_boot.fraction_non_positive if date_boot else None)}",
            "",
            "IID / SECTOR SENSITIVITY",
            f"iid_two_sided_p: {_fmt(iid_perm.two_sided_p if iid_perm else None)}",
            f"iid_ci: [{_fmt(iid_boot.lower if iid_boot else None)}, {_fmt(iid_boot.upper if iid_boot else None)}]",
            f"sector_ci: [{_fmt(sector_boot.lower if sector_boot else None)}, {_fmt(sector_boot.upper if sector_boot else None)}]",
            "",
            "PLACEBO DIAGNOSTIC",
            f"original_mean_edge: {_fmt(placebo.original_mean_edge if placebo else None)}",
            f"placebo_mean_edge: {_fmt(placebo.placebo_mean_edge if placebo else None)}",
            "",
            "CONCENTRATION ROBUSTNESS",
            f"top1_positive_share: {_fmt(concentration.top1_positive_share if concentration else None)}",
            f"top5_positive_share: {_fmt(concentration.top5_positive_share if concentration else None)}",
            f"strongest_symbol: {concentration.symbol_stress.strongest_group if concentration else 'unavailable'}",
            f"mean_after_remove_strongest_symbol: {_fmt(concentration.symbol_stress.mean_after_remove_strongest if concentration else None)}",
            f"strongest_sector: {concentration.sector_stress.strongest_group if concentration else 'unavailable'}",
            f"mean_after_remove_strongest_sector: {_fmt(concentration.sector_stress.mean_after_remove_strongest if concentration else None)}",
            f"strongest_year: {concentration.year_stress.strongest_group if concentration else 'unavailable'}",
            f"mean_after_remove_strongest_year: {_fmt(concentration.year_stress.mean_after_remove_strongest if concentration else None)}",
            f"strongest_regime: {concentration.regime_stress.strongest_group if concentration else 'unavailable'}",
            f"mean_after_remove_strongest_regime: {_fmt(concentration.regime_stress.mean_after_remove_strongest if concentration else None)}",
            f"symbol_hhi: {_fmt(concentration.symbol_hhi if concentration else None)}",
            f"sector_hhi: {_fmt(concentration.sector_hhi if concentration else None)}",
            "",
            "EXECUTION SURVIVABILITY",
            f"cost_curve_r: {_fmt_curve(execution.cost_curve_r if execution else {})}",
            f"break_even_bps: {_fmt(execution.break_even_bps if execution else None)}",
            f"atr_slippage_curve_r: {_fmt_curve(execution.atr_slippage_curve_r if execution else {})}",
            f"break_even_atr_fraction: {_fmt(execution.break_even_atr_fraction if execution else None)}",
            f"delay_curve_r: {_fmt_curve(execution.delay_curve_r if execution else {})}",
            f"combined_realistic_r: {_fmt(execution.combined_realistic_r if execution else None)}",
            f"mean_entry_gap_penalty_r: {_fmt(execution.mean_entry_gap_penalty_r if execution else None)}",
            f"mean_stop_gap_penalty_r: {_fmt(execution.mean_stop_gap_penalty_r if execution else None)}",
            "",
            "TRIAL / DATA IDENTITY",
            f"trial_ids: {', '.join(bundle.trial_ids) if bundle.trial_ids else 'none'}",
            f"sample_start: {bundle.sample_start.isoformat()}",
            f"sample_end: {bundle.sample_end.isoformat()}",
            "",
            "RESEARCH STATUS",
            bundle.status.value.upper(),
            f"reasons: {reasons}",
            "This statistical evidence package is not a strategy promotion verdict.",
            "",
        ]
    )
