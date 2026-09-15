from __future__ import annotations

from typing import Iterable, Sequence

from morning_alpha.audit import SignalScorecard
from morning_alpha.models import SignalOutcome
from morning_alpha.service import ScanResult, ScanStatus


SECTION_ORDER = (
    "PRIOR RUN AUDIT",
    "ROLLING SIGNAL SCORECARD",
    "MARKET REGIME",
    "QUALIFYING SETUPS",
    "PORTFOLIO HEAT",
    "UNVERIFIED / INFERRED NOTES",
)


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_morning_report(
    scan: ScanResult,
    prior_audit: Iterable[SignalOutcome] = (),
    scorecard: SignalScorecard | None = None,
    *,
    notes: Sequence[str] = (),
) -> str:
    if scan.status is ScanStatus.NO_TRADE:
        return "NO_TRADE"

    audits = list(prior_audit)
    lines: list[str] = []

    lines.append("PRIOR RUN AUDIT")
    if not audits:
        lines.append("No prior-run audit records available.")
    else:
        for row in audits:
            state = row.classification.value.upper()
            trigger = "TRIGGERED" if row.triggered else "NO TRADE"
            lines.append(
                f"{row.symbol}: {trigger} | {state} | close={_fmt(row.close_r)}R | "
                f"MFE={_fmt(row.mfe_r)}R | MAE={_fmt(row.mae_r)}R"
            )

    lines.extend(["", "ROLLING SIGNAL SCORECARD"])
    if scorecard is None:
        lines.append("No rolling scorecard available.")
    else:
        lines.append(
            f"candidates={scorecard.total_candidates} triggered={scorecard.triggers_fired} "
            f"wins={scorecard.wins} losses={scorecard.losses} open={scorecard.open_or_unfinished}"
        )
        lines.append(
            f"filtered_losers={scorecard.filtered_losers} "
            f"filtered_winners={scorecard.filtered_winners} unverified={scorecard.unverified}"
        )
        lines.append(
            f"cumulative_marked_R={scorecard.cumulative_r:.2f} "
            f"avg_MFE={_fmt(scorecard.average_mfe_r)}R avg_MAE={_fmt(scorecard.average_mae_r)}R"
        )

    lines.extend(["", "MARKET REGIME"])
    if scan.regime is None:
        lines.append("[Unverified] No structured regime record was supplied for this scan.")
    else:
        lines.append(
            f"risk_state={scan.regime.risk_state} SPY={scan.regime.spy_trend} "
            f"QQQ={scan.regime.qqq_trend} VIX={scan.regime.vix_bucket}"
        )

    lines.extend(["", "QUALIFYING SETUPS"])
    for plan in scan.qualified_plans:
        targets = ", ".join(f"{x:.2f}" for x in plan.targets)
        lines.append(
            f"{plan.symbol} | {plan.strategy.canonical} | [Inference] entry={plan.entry:.2f} "
            f"stop={plan.stop:.2f} targets={targets} expected={plan.expected_r:.2f}R "
            f"shares={plan.shares} max_risk=${plan.max_dollar_risk:.2f}"
        )

    lines.extend(["", "PORTFOLIO HEAT"])
    lines.append(f"initial_heat={scan.portfolio_decision.total_heat:.2%}")
    for theme, heat in scan.portfolio_decision.theme_heat.items():
        lines.append(f"theme={theme} heat={heat:.2%}")

    lines.extend(["", "UNVERIFIED / INFERRED NOTES"])
    lines.append(
        "[Inference] Entries, stops, targets, and expected R are deterministic technical constructions."
    )
    if not notes:
        lines.append("No additional unverified notes.")
    else:
        lines.extend(notes)

    return "\n".join(lines).rstrip() + "\n"
