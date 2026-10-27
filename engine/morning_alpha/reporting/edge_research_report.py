from __future__ import annotations

from morning_alpha.research.relative_strength_sprint import RelativeStrengthSprintReport

EDGE_RESEARCH_SECTION_ORDER = (
    "SAMPLE / CONTROLS",
    "RAW FORWARD RETURNS",
    "SELECTION ALPHA",
    "TRIGGER COMPARISON",
    "MFE / MAE",
    "EXIT STUDY",
    "ABLATIONS",
    "REGIME / ROBUSTNESS",
    "COST / OOS / WFO",
    "TRIAL COUNT",
    "GATE V2",
    "CONCLUSION",
)


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.4f}%"


def render_edge_research_report(report: RelativeStrengthSprintReport) -> str:
    lines: list[str] = [
        f"RELATIVE STRENGTH RESEARCH — {report.strategy_key}",
        "",
        "SAMPLE / CONTROLS",
    ]
    for name in sorted(report.control_counts):
        lines.append(
            f"{name}: count={report.control_counts[name]} symbol={report.control_symbols.get(name) or 'N/A'}"
        )

    lines += ["", "RAW FORWARD RETURNS"]
    for name in sorted(report.forward_returns):
        lines.append(f"{name}: {_fmt_pct(report.forward_returns[name])}")

    lines += ["", "SELECTION ALPHA"]
    if report.attribution is None:
        lines.append("Unavailable: attribution inputs missing.")
    else:
        for name, value in report.attribution.components.items():
            lines.append(f"{name}: {value:.6f}")
        lines.append(f"total_increment: {report.attribution.total_increment:.6f}")

    lines += [
        "",
        "TRIGGER COMPARISON",
        "Pending full validation stage.",
        "",
        "MFE / MAE",
        "Pending full validation stage.",
        "",
        "EXIT STUDY",
        "Pending full validation stage.",
        "",
        "ABLATIONS",
        "Pending full validation stage.",
        "",
        "REGIME / ROBUSTNESS",
        "Pending full validation stage.",
        "",
        "COST / OOS / WFO",
        "Pending full validation stage.",
        "",
        "TRIAL COUNT",
        str(len(report.trial_ids)),
        "",
        "GATE V2",
        "Pending full validation stage.",
        "",
        "CONCLUSION",
        report.status.value.upper(),
    ]
    if report.reasons:
        lines.append("Reasons: " + ", ".join(report.reasons))
    return "\n".join(lines) + "\n"
