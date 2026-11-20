"""Gate v2 orchestrator — runs the dual-pathway validator against a research
config and aux-evidence reports, persists a consolidated verdict snapshot.

Phase 2 implementation of `project_gate_v2_proposal.md`. Called by:
  * The weekly cron in `engine/main.py` (Saturday 01:00 CT)
  * Ad-hoc from CLI when a new strategy candidate needs gate re-scoring

Aux-evidence naming convention (auto-discovery in `reports_dir`):
    {SYMBOL}_{family}_rank{rank}_rolling_wfo.json
    {SYMBOL}_{family}_fixed_params_temporal.json
    {SYMBOL}_{family}_rank{rank}_cost_sweep.json

Output path:
    {output_dir}/{SYMBOL}_{family}_rank{rank}.json

If any aux report is missing, alt path scores as UNSCORED and the verdict
is driven by the core gate alone. Freshness (mtime) of each aux report is
recorded in `aux_freshness` for downstream staleness checks.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from scripts.validate_strategy import (  # noqa: E402
    _evaluate_gate_v2,
    _extract_pnls,
    _load_result,
    validate,
)

logger = logging.getLogger(__name__)


@dataclass
class VerdictSnapshot:
    """Persisted consolidated gate v2 verdict for one strategy config.

    This is what the weekly cron writes and what `gate_v2_policy` reads.
    """
    symbol: str
    family: str
    rank: int
    verdict: str                         # "PASS" | "FAIL"
    passed_via: Optional[str]            # "core" | "alt" | None
    core_verdict: str                    # "PASS" | "FAIL"
    alt_verdict: str                     # "PASS" | "FAIL" | "UNSCORED"
    n_core_passed: int
    n_alt_passed: int
    created_at: str                      # ISO-8601
    aux_freshness: dict[str, Optional[str]]  # {"rolling_wfo": ISO-ts | None, ...}
    gate_v2: dict[str, Any]              # full evaluation dict (reasons, etc.)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> "VerdictSnapshot":
        return cls(
            symbol=doc["symbol"],
            family=doc["family"],
            rank=doc["rank"],
            verdict=doc["verdict"],
            passed_via=doc.get("passed_via"),
            core_verdict=doc["core_verdict"],
            alt_verdict=doc["alt_verdict"],
            n_core_passed=doc["n_core_passed"],
            n_alt_passed=doc["n_alt_passed"],
            created_at=doc["created_at"],
            aux_freshness=doc.get("aux_freshness", {}),
            gate_v2=doc.get("gate_v2", {}),
        )


def resolve_aux_paths(
    reports_dir: Path, symbol: str, family: str, rank: int
) -> dict[str, Optional[Path]]:
    """Look up the 3 aux-evidence files by naming convention. Missing files
    return None — orchestrator downgrades alt path to UNSCORED."""
    candidates = {
        "rolling_wfo":
            reports_dir / f"{symbol}_{family}_rank{rank}_rolling_wfo.json",
        "fixed_params":
            reports_dir / f"{symbol}_{family}_fixed_params_temporal.json",
        "cost_sweep":
            reports_dir / f"{symbol}_{family}_rank{rank}_cost_sweep.json",
    }
    return {k: (p if p.exists() else None) for k, p in candidates.items()}


def _load_aux_evidence(
    aux_paths: dict[str, Optional[Path]]
) -> tuple[Optional[dict], dict[str, Optional[str]]]:
    """Read aux inputs from the resolved paths. Returns (aux_dict, freshness).

    `aux_dict` is None when any file is missing (alt path unscored).
    `freshness` maps each channel to its file mtime ISO-8601 (or None).
    """
    freshness: dict[str, Optional[str]] = {}
    for name, path in aux_paths.items():
        if path is not None and path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            freshness[name] = mtime.isoformat()
        else:
            freshness[name] = None

    if not all(v is not None for v in aux_paths.values()):
        return None, freshness

    aux: dict[str, Any] = {}
    with open(aux_paths["rolling_wfo"]) as f:
        aux["rolling_wfo_verdict"] = json.load(f).get("verdict")
    with open(aux_paths["fixed_params"]) as f:
        stats = (json.load(f).get("stats") or {})
        aux["fixed_params_min_pf"] = stats.get("min_pf")
    with open(aux_paths["cost_sweep"]) as f:
        aux["cost_survives_through"] = json.load(f).get("edge_survives_through")

    # If any parsed value is None, degrade to unscored rather than crash.
    if any(v is None for v in aux.values()):
        return None, freshness
    return aux, freshness


def orchestrate_gate_v2(
    results_file: Path,
    symbol: str,
    family: str,
    rank: int,
    reports_dir: Path,
    output_dir: Path,
    n_resamples: int = 10_000,
    initial_capital: float = 10_000.0,
    seed: int = 42,
) -> VerdictSnapshot:
    """Run the dual-pathway gate v2 for one config and persist the verdict.

    Returns the VerdictSnapshot — also written to
    `output_dir/{SYMBOL}_{family}_rank{rank}.json` as a JSON record
    consumed by the policy module at read time.
    """
    results_file = Path(results_file)
    reports_dir = Path(reports_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    loaded = _load_result(results_file, rank)
    pnls = _extract_pnls(loaded["combo"])
    report = validate(
        pnls,
        n_grid_trials=loaded["n_grid_trials"],
        initial_capital=initial_capital,
        n_resamples=n_resamples,
        seed=seed,
    )

    aux_paths = resolve_aux_paths(reports_dir, symbol, family, rank)
    aux_evidence, freshness = _load_aux_evidence(aux_paths)
    gate = _evaluate_gate_v2(report, aux_evidence=aux_evidence)

    snap = VerdictSnapshot(
        symbol=symbol,
        family=family,
        rank=rank,
        verdict=gate["verdict"],
        passed_via=gate["passed_via"],
        core_verdict=gate["core_verdict"],
        alt_verdict=gate["alt_verdict"],
        n_core_passed=gate["n_core_passed"],
        n_alt_passed=gate["n_alt_passed"],
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        aux_freshness=freshness,
        gate_v2=gate,
    )

    outfile = output_dir / f"{symbol}_{family}_rank{rank}.json"
    outfile.write_text(json.dumps(snap.to_dict(), indent=2))
    logger.info(
        "[GateV2Orchestrator] %s/%s rank=%d verdict=%s via=%s → %s",
        symbol, family, rank, snap.verdict, snap.passed_via, outfile,
    )
    return snap


# ---------------------------------------------------------- #
# CLI                                                        #
# ---------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate v2 orchestrator (Phase 2)")
    ap.add_argument("--results-file", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--family", required=True, choices=["trend", "meanrev", "breakout", "options"])
    ap.add_argument("--rank", type=int, default=1)
    ap.add_argument(
        "--reports-dir",
        default=str(_ENGINE / "scripts" / "validation_reports"),
        help="Directory containing aux validator reports",
    )
    ap.add_argument("--output-dir",
        default=str(_ENGINE / "data" / "gate_v2_verdicts"),
        help="Directory to write consolidated verdict JSON",
    )
    ap.add_argument("--initial-capital", type=float, default=10_000.0)
    ap.add_argument("--n-resamples", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    snap = orchestrate_gate_v2(
        results_file=Path(args.results_file),
        symbol=args.symbol,
        family=args.family,
        rank=args.rank,
        reports_dir=Path(args.reports_dir),
        output_dir=Path(args.output_dir),
        initial_capital=args.initial_capital,
        n_resamples=args.n_resamples,
        seed=args.seed,
    )
    print(
        f"[GateV2Orchestrator] {snap.symbol}/{snap.family} rank={snap.rank} "
        f"verdict={snap.verdict} via={snap.passed_via or '—'} "
        f"core={snap.n_core_passed}/4 alt={snap.n_alt_passed}/5"
    )
    return 0 if snap.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
