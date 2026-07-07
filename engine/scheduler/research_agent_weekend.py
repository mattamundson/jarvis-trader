"""
Weekend research pass — off-pipeline strategy hypothesis cron.

Entry point: run_weekend_research_pass(symbols, n_hypotheses_per_symbol)

For each symbol:
  1. Calls ResearchAgent.propose() N times (haiku tier, cost-gated).
  2. Each hypothesis is checked against the gate-v2 verdict advisory read.
     Hypotheses for which a non-stale PASS verdict already exists in
     engine/data/gate_v2_verdicts/ are noted as "reinforcing" in the summary;
     others are "candidate" (novel, needs backtest run).
  3. Surviving hypotheses written to
     engine/data/research_hypotheses/<YYYY-MM-DD>/<symbol>-<n>.json
  4. Markdown summary appended to
     master-jarvis/second-brain/raw/_session-research/research-pass-<date>.md

Designed to run from a Windows Scheduled Task (Saturday 10:00 CT):
    pwsh.exe -NonInteractive -File scripts/run_research_agent_weekend.py

ENABLE_RESEARCH_AGENT must be set to 1 for LLM calls to fire; when unset the
stub fallback runs (still exercises the artifact write path for smoke-testing).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Root of the engine package (engine/scheduler/ -> engine/)
_ENGINE_ROOT = Path(__file__).resolve().parent.parent

_HYPOTHESES_DIR = _ENGINE_ROOT / "data" / "research_hypotheses"

# Vault summary path — relative to the jarvis-trader repo root
_VAULT_SUMMARY_DIR = (
    _ENGINE_ROOT.parent / "master-jarvis" / "second-brain" / "raw" / "_session-research"
)


# ---------------------------------------------------------------------------
# Gate-v2 advisory check (read-only, non-blocking)
# ---------------------------------------------------------------------------


def _has_passing_verdict(symbol: str) -> bool:
    """
    Return True if there is a non-stale PASS gate-v2 verdict for *symbol*.

    Uses the read-only backtest.gate_v2_policy module.  Never raises — returns
    False on import failure so the cron continues without gate-v2.
    """
    try:
        from backtest.gate_v2_policy import is_ungate_eligible  # lazy import

        return is_ungate_eligible(symbol)
    except Exception as exc:
        logger.debug("gate_v2_policy unavailable (%s) — treating as no PASS", exc)
        return False


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def _write_hypothesis_json(
    hypothesis: Any,
    output_dir: Path,
    index: int,
) -> Path:
    """
    Write a StrategyHypothesis to a dated JSON file and return the path.

    Output: <output_dir>/<symbol>-<index>.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{hypothesis.symbol.upper()}-{index}.json"
    dest = output_dir / filename

    data = hypothesis.model_dump()
    data["generated_at"] = datetime.now(tz=timezone.utc).isoformat()
    dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("research_agent_weekend: wrote %s", dest)
    return dest


def _append_markdown_summary(
    summary_path: Path,
    run_date: str,
    symbol_results: list[dict[str, Any]],
) -> None:
    """
    Append a Markdown section to the research-pass summary file.

    Creates the file (and parent directories) if not present.
    Appends a new dated section each run — multiple runs accumulate in one file.
    """
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "",
        f"## Research pass — {run_date} (appended {datetime.now(tz=timezone.utc).strftime('%H:%M UTC')})",
        "",
    ]

    for sr in symbol_results:
        symbol = sr["symbol"]
        hypotheses = sr.get("hypotheses", [])
        gate_pass = sr.get("gate_pass", False)
        status_tag = "(gate-v2 PASS — reinforcing)" if gate_pass else "(candidate — needs backtest)"
        lines.append(f"### {symbol} {status_tag}")
        lines.append("")

        if not hypotheses:
            lines.append("_No hypotheses generated (flag off or budget exhausted)._")
            lines.append("")
            continue

        for i, h in enumerate(hypotheses, start=1):
            lines.append(f"**Hypothesis {i}:** `{h.name}` — {h.timeframe}")
            lines.append("")
            lines.append(f"- **Rationale:** {h.rationale}")
            lines.append(f"- **Entry rules:** {'; '.join(h.entry_rules)}")
            lines.append(f"- **Exit rules:** {'; '.join(h.exit_rules)}")
            if h.risk_params:
                rp = ", ".join(f"{k}={v}" for k, v in h.risk_params.items())
                lines.append(f"- **Risk params:** {rp}")
            lines.append(f"- **Agent confidence:** {h.confidence:.2f} (gate-v2 will re-score)")
            if sr.get("json_paths"):
                json_rel = sr["json_paths"][i - 1] if i - 1 < len(sr["json_paths"]) else ""
                if json_rel:
                    lines.append(f"- **JSON:** `{json_rel}`")
            lines.append("")

    lines.append("---")
    lines.append("")

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("research_agent_weekend: appended summary to %s", summary_path)


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def run_weekend_research_pass(
    symbols: list[str],
    n_hypotheses_per_symbol: int = 3,
) -> dict[str, Any]:
    """
    Run a full weekend research pass for the given symbols.

    Args:
        symbols:                   List of root futures symbols, e.g. ["MES", "MNQ"].
        n_hypotheses_per_symbol:   How many hypotheses to request per symbol.
                                   Capped at 5 to bound cost.

    Returns:
        A summary dict with keys: run_date, total_generated, total_written,
        symbol_results, summary_path.
    """
    from agents.research_agent import ResearchAgent  # lazy import — avoids circular

    n_hypotheses_per_symbol = min(n_hypotheses_per_symbol, 5)
    run_date = date.today().isoformat()
    output_dir = _HYPOTHESES_DIR / run_date
    summary_path = _VAULT_SUMMARY_DIR / f"research-pass-{run_date}.md"

    agent = ResearchAgent()
    symbol_results: list[dict[str, Any]] = []
    total_generated = 0
    total_written = 0

    for symbol in symbols:
        logger.info(
            "research_agent_weekend: processing %s (%d hyps)", symbol, n_hypotheses_per_symbol
        )
        gate_pass = _has_passing_verdict(symbol)
        hypotheses = []
        json_paths: list[str] = []

        for n in range(1, n_hypotheses_per_symbol + 1):
            try:
                hyp = await agent.propose(symbol, context={"regime": None})
                hypotheses.append(hyp)
                total_generated += 1

                dest = _write_hypothesis_json(hyp, output_dir, n)
                # Store path relative to engine root for readability in summary
                try:
                    rel = str(dest.relative_to(_ENGINE_ROOT.parent))
                except ValueError:
                    rel = str(dest)
                json_paths.append(rel)
                total_written += 1

            except Exception as exc:
                logger.warning(
                    "research_agent_weekend: propose failed for %s #%d: %s",
                    symbol,
                    n,
                    exc,
                )

        symbol_results.append(
            {
                "symbol": symbol,
                "hypotheses": hypotheses,
                "gate_pass": gate_pass,
                "json_paths": json_paths,
            }
        )

    _append_markdown_summary(summary_path, run_date, symbol_results)

    summary = {
        "run_date": run_date,
        "total_generated": total_generated,
        "total_written": total_written,
        "symbol_results": [
            {
                "symbol": sr["symbol"],
                "n_hypotheses": len(sr["hypotheses"]),
                "gate_pass": sr["gate_pass"],
                "json_paths": sr["json_paths"],
            }
            for sr in symbol_results
        ],
        "summary_path": str(summary_path),
    }
    logger.info("research_agent_weekend: pass complete — %s", summary)
    return summary
