"""
GEPA runner CLI — jarvis-trader Pilot 1 (compound-agent-system)
==================================================================

Binds GEPAOptimizer (engine/llm/prompt_evolution.py) to real trade data via
gepa_bindings.py and emits a Pareto-frontier JSON artifact. Read-only against
agent_feedback.db. Never writes to engine/agents/*.py — a winning candidate
is a proposal artifact only; promoting it requires a human-authored PR.

Usage:
    .venv/Scripts/python -m engine.llm.gepa_runner \\
        --target-agent bull_researcher --n-generations 1 --out artifact.json \\
        [--db-path C:\\path\\to\\agent_feedback.db]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from llm.gepa_bindings import SonnetPromptMutator, SonnetPromptScorer, SqliteTradeEvalSource
from llm.prompt_evolution import GEPAOptimizer

TARGET_AGENTS = {
    "bull_researcher": ("agents.bull_researcher", "BullResearcherAgent", "SYSTEM_PROMPT"),
    "bear_researcher": ("agents.bear_researcher", "BearResearcherAgent", "SYSTEM_PROMPT"),
}


def _load_base_prompt(target_agent: str) -> str:
    """Reads the live SYSTEM_PROMPT constant from the target agent's own module —
    single source of truth, never a duplicated copy that can drift."""
    module_name, class_name, attr_name = TARGET_AGENTS[target_agent]
    import importlib
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return getattr(cls, attr_name)


async def run(target_agent: str, n_generations: int, eval_sample_size: int,
              db_path: Path | None, out_path: Path) -> dict:
    base_prompt = _load_base_prompt(target_agent)

    optimizer = GEPAOptimizer(
        base_prompt=base_prompt,
        eval_source=SqliteTradeEvalSource(db_path=db_path),
        mutator=SonnetPromptMutator(),
        scorer=SonnetPromptScorer(),
        eval_sample_size=eval_sample_size,
    )
    frontier = await optimizer.evolve(n_generations=n_generations, variants_per_member=2, max_frontier_size=8)

    artifact = {
        "target_agent": target_agent,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_generations": n_generations,
        "eval_sample_size": eval_sample_size,
        "base_prompt_candidate_id": None,
        "frontier": [c.to_dict() for c in frontier.members],
        "history": optimizer.history,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="GEPA prompt-evolution runner (Pilot 1)")
    parser.add_argument("--target-agent", choices=sorted(TARGET_AGENTS), default="bull_researcher")
    parser.add_argument("--n-generations", type=int, default=1)
    parser.add_argument("--eval-sample-size", type=int, default=30)
    parser.add_argument("--db-path", type=str, default=None,
                        help="Override agent_feedback.db path (default: AgentFeedbackTracker's own resolution)")
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else None
    artifact = asyncio.run(run(
        target_agent=args.target_agent,
        n_generations=args.n_generations,
        eval_sample_size=args.eval_sample_size,
        db_path=db_path,
        out_path=Path(args.out),
    ))

    n_evals_total = sum(c["n_evals"] for c in artifact["frontier"])
    if not artifact["frontier"] or n_evals_total == 0:
        print(f"LOOP_STATUS: ERROR — empty frontier or zero evals (frontier size={len(artifact['frontier'])})", file=sys.stderr)
        return 1
    print(f"Frontier size: {len(artifact['frontier'])}, total evals: {n_evals_total}")
    print(f"Best accuracy: {max(c['accuracy'] for c in artifact['frontier']):.3f}")
    print(f"Artifact written to: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
