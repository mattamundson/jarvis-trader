"""
Weekend research pass — off-pipeline strategy hypothesis cron.

Two entry points:
  - run_weekend_research_pass(symbols, n_hypotheses_per_symbol) — original
    synchronous path: calls ResearchAgent.propose() N times per symbol
    in-process and writes artifacts immediately. Still used by
    test_weekend_pass_writes_artifacts and available for manual/ad-hoc runs.
  - run_weekend_research_pass_submit(...) / run_weekend_research_pass_collect()
    — batch-API split (see engine/llm/batch_client.py): submit builds one
    Anthropic Message Batch for every (symbol, n) request and returns
    immediately; collect reads harvested results (via the batch_poll_sweep
    cron) up to a day later and writes the same artifacts. Half the token
    cost of the synchronous path, at the cost of a 1-24h delay before the
    weekend's hypotheses are available — acceptable for a Saturday-morning
    research cron whose output isn't needed same-day. This is the path
    wired into APScheduler in engine/main.py; the synchronous path remains
    for manual invocation only.

For each symbol:
  1. Generates N hypotheses (haiku tier, cost-gated against
     research_agent_costs — see ResearchAgent.has_budget_for).
  2. Each hypothesis is checked against the gate-v2 verdict advisory read.
     Hypotheses for which a non-stale PASS verdict already exists in
     engine/data/gate_v2_verdicts/ are noted as "reinforcing" in the summary;
     others are "candidate" (novel, needs backtest run).
  3. Surviving hypotheses written to
     engine/data/research_hypotheses/<YYYY-MM-DD>/<symbol>-<n>.json
  4. Markdown summary appended to
     master-jarvis/second-brain/raw/_session-research/research-pass-<date>.md

ENABLE_RESEARCH_AGENT must be set to 1 for LLM calls to fire; when unset the
stub fallback runs (still exercises the artifact write path for smoke-testing).

Batch failure policy for the submit/collect path (see batch_client.py module
docstring for the full tiering): submission failure is "skip" (next
Saturday's cron simply tries again — low-stakes weekly research); individual
errored/canceled/expired items and stale (>25h) batches always get a
per-item synchronous fallback via ResearchAgent.propose(), so the weekly
markdown summary stays complete even when a handful of batch items fail.
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


# ---------------------------------------------------------------------------
# Batch API split — submit builds+submits one batch and returns immediately;
# collect reads harvested results (possibly a scheduler cron cycle or a day
# later) and writes the same artifacts as run_weekend_research_pass above.
# ---------------------------------------------------------------------------

# custom_id format: "<run_date>__<symbol>__<n>" — "__" never appears in a
# run_date (YYYY-MM-DD) or a futures root symbol, so splitting on it is
# unambiguous. Anthropic custom_id must match [a-zA-Z0-9_-]{1,64}; no colons.
_CUSTOM_ID_SEP = "__"


def _make_custom_id(run_date: str, symbol: str, n: int) -> str:
    return f"{run_date}{_CUSTOM_ID_SEP}{symbol}{_CUSTOM_ID_SEP}{n}"


def _parse_custom_id(custom_id: str) -> tuple[str, str, int]:
    run_date, symbol, n_str = custom_id.split(_CUSTOM_ID_SEP)
    return run_date, symbol, int(n_str)


async def run_weekend_research_pass_submit(
    symbols: list[str],
    n_hypotheses_per_symbol: int = 3,
) -> dict[str, Any]:
    """
    Build every (symbol, n) research prompt and submit them as one Message
    Batch. Returns immediately — does not wait for the batch to complete.

    Tier-1 failure policy: if the pre-submission budget check fails or
    submit_batch() itself raises, this returns submitted=False and skips —
    next Saturday's cron simply tries again (see module docstring).
    """
    from agents.research_agent import _HAIKU_MODEL, _SYSTEM_PROMPT, ResearchAgent  # lazy import
    from llm.batch_client import JarvisBatchClient

    n_hypotheses_per_symbol = min(n_hypotheses_per_symbol, 5)
    run_date = date.today().isoformat()
    total_requests = len(symbols) * n_hypotheses_per_symbol

    agent = ResearchAgent()
    if not agent.has_budget_for(total_requests):
        logger.warning(
            "research_agent_weekend: submit skipped — insufficient research_agent_costs "
            "budget for %d requests",
            total_requests,
        )
        return {"submitted": False, "reason": "budget_exhausted", "run_date": run_date}

    batch_client = JarvisBatchClient()
    requests = []
    for symbol in symbols:
        for n in range(1, n_hypotheses_per_symbol + 1):
            prompt = agent.build_prompt(symbol, context={"regime": None})
            requests.append(
                batch_client.build_request(
                    custom_id=_make_custom_id(run_date, symbol, n),
                    model=_HAIKU_MODEL,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    shared_system_cache=True,
                )
            )

    try:
        batch_id = await batch_client.submit_batch(agent_name="research_agent", requests=requests)
    except Exception as exc:
        logger.warning("research_agent_weekend: submit_batch failed (%s) — skipping this week", exc)
        return {"submitted": False, "reason": str(exc), "run_date": run_date}

    logger.info(
        "research_agent_weekend: submitted batch %s for %d symbols x %d hyps (run_date=%s)",
        batch_id,
        len(symbols),
        n_hypotheses_per_symbol,
        run_date,
    )
    return {
        "submitted": True,
        "batch_id": batch_id,
        "run_date": run_date,
        "symbols": symbols,
        "request_count": len(requests),
    }


async def run_weekend_research_pass_collect() -> dict[str, Any]:
    """
    Collect results for every not-yet-fully-consumed research_agent batch.

    For each such batch: ensures results are harvested (polls once if the
    batch_poll_sweep cron hasn't caught it yet), reads unconsumed
    batch_results rows, parses succeeded items into StrategyHypothesis,
    synchronously falls back (ResearchAgent.propose) any errored/canceled/
    expired item so the weekly output stays complete, writes the same JSON
    artifacts + markdown summary as run_weekend_research_pass, and marks
    every processed row consumed.

    Safe to run multiple times (e.g. Sat 16:00 CT and Sun 08:00 CT) — a
    batch with nothing new to collect is a no-op.
    """
    from agents.research_agent import ResearchAgent  # lazy import — avoids circular
    from llm.batch_client import JarvisBatchClient

    batch_client = JarvisBatchClient()
    agent = ResearchAgent()
    jobs = batch_client.list_jobs(agent_name="research_agent")

    collected_runs: list[dict[str, Any]] = []

    for job in jobs:
        batch_id = job["batch_id"]

        if job["status"] in ("stale_collected",):
            continue  # already fully handled by a prior collect() call

        if job["status"] == "stale":
            # Tier-3 fallback: never ended within the grace period. Handled
            # entirely here (not via batch_results/_collect_ended_batch) so
            # a repeat collect() call can't re-run the fallback and burn
            # cost twice — mark_job_status makes this branch a one-shot.
            run_summary = await _collect_stale_batch(agent, batch_id, job)
            if run_summary is not None:
                collected_runs.append(run_summary)
            batch_client.mark_job_status(batch_id, "stale_collected")
            continue

        if job["status"] != "ended":
            status = await batch_client.poll_batch(batch_id)
            if status != "ended":
                continue  # not ready yet — try again next collect cycle
            await batch_client.collect_results(batch_id)

        run_summary = await _collect_ended_batch(batch_client, agent, batch_id)
        if run_summary is not None:
            collected_runs.append(run_summary)

    return {"collected_runs": collected_runs}


async def _collect_stale_batch(
    agent: Any,
    batch_id: str,
    job: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Synchronously replay every custom_id in a stale batch via
    ResearchAgent.propose() (full sync cost accounting, no batch discount —
    this is the cost of the batch never completing) and write the same
    artifacts as the ended-batch path.
    """
    request_meta: dict[str, str] = json.loads(job["request_meta_json"])
    logger.warning(
        "research_agent_weekend: batch %s stale — sync-falling-back %d items",
        batch_id,
        len(request_meta),
    )

    by_run: dict[str, dict[str, list[tuple[int, Any]]]] = {}
    for custom_id in request_meta:
        run_date, symbol, n = _parse_custom_id(custom_id)
        hypothesis = await agent.propose(symbol, context={"regime": None})
        by_run.setdefault(run_date, {}).setdefault(symbol, []).append((n, hypothesis))

    return _write_batch_artifacts(by_run, batch_id)


async def _collect_ended_batch(
    batch_client: Any,
    agent: Any,
    batch_id: str,
) -> dict[str, Any] | None:
    """Parse unconsumed results for one ended/stale batch and write artifacts."""
    from agents.research_agent import _HAIKU_MODEL  # lazy import
    from llm.client import JarvisLLMClient

    unconsumed = batch_client.get_unconsumed_results(batch_id)
    if not unconsumed:
        return None

    llm_client = JarvisLLMClient()
    by_run: dict[str, dict[str, list[tuple[int, Any]]]] = {}
    consumed_ids: list[str] = []

    for custom_id, item in unconsumed.items():
        run_date, symbol, n = _parse_custom_id(custom_id)

        if item.result_type == "succeeded":
            hypothesis = agent.parse_hypothesis(item.content, symbol=symbol)
            await batch_client.log_batch_cost(
                llm_client,
                model=_HAIKU_MODEL,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                agent_name="research_agent",
            )
            agent.record_spend(
                batch_client.calculate_batch_cost(
                    _HAIKU_MODEL, item.input_tokens, item.output_tokens
                )
            )
        else:
            logger.warning(
                "research_agent_weekend: batch %s item %s was %s — sync fallback",
                batch_id,
                custom_id,
                item.result_type,
            )
            hypothesis = await agent.propose(symbol, context={"regime": None})

        by_run.setdefault(run_date, {}).setdefault(symbol, []).append((n, hypothesis))
        consumed_ids.append(custom_id)

    await llm_client.close()
    batch_client.mark_consumed(batch_id, consumed_ids)

    return _write_batch_artifacts(by_run, batch_id)


def _write_batch_artifacts(
    by_run: dict[str, dict[str, list[tuple[int, Any]]]],
    batch_id: str,
) -> dict[str, Any]:
    """
    Shared artifact writer for both the ended-batch and stale-batch collect
    paths: writes per-symbol JSON files + appends the markdown summary,
    exactly matching run_weekend_research_pass's output shape.
    """
    run_summaries = []
    for run_date, by_symbol in by_run.items():
        output_dir = _HYPOTHESES_DIR / run_date
        summary_path = _VAULT_SUMMARY_DIR / f"research-pass-{run_date}.md"
        symbol_results = []
        total_written = 0

        for symbol, indexed_hyps in by_symbol.items():
            indexed_hyps.sort(key=lambda pair: pair[0])
            gate_pass = _has_passing_verdict(symbol)
            json_paths: list[str] = []
            hypotheses = []
            for n, hypothesis in indexed_hyps:
                dest = _write_hypothesis_json(hypothesis, output_dir, n)
                try:
                    rel = str(dest.relative_to(_ENGINE_ROOT.parent))
                except ValueError:
                    rel = str(dest)
                json_paths.append(rel)
                hypotheses.append(hypothesis)
                total_written += 1

            symbol_results.append(
                {
                    "symbol": symbol,
                    "hypotheses": hypotheses,
                    "gate_pass": gate_pass,
                    "json_paths": json_paths,
                }
            )

        _append_markdown_summary(summary_path, run_date, symbol_results)
        run_summaries.append(
            {
                "run_date": run_date,
                "batch_id": batch_id,
                "total_written": total_written,
                "summary_path": str(summary_path),
            }
        )
        logger.info(
            "research_agent_weekend: collected batch %s — run_date=%s total_written=%d",
            batch_id,
            run_date,
            total_written,
        )

    return {"batch_id": batch_id, "runs": run_summaries}
