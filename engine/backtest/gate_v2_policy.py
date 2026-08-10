"""Gate v2 policy — advisory read-side for persisted gate v2 verdicts.

Phase 3 LIGHT implementation (`project_gate_v2_proposal.md`). Read-only
helpers for dashboards, cron logs, and future hard-enforcement work. This
module DOES NOT block trading routing — it exposes eligibility signals that
the rest of the codebase can advisorily consult.

Contract:
  * `get_last_verdict(symbol) -> VerdictSnapshot | None` — newest non-stale
     verdict across all rank files for `symbol`.
  * `is_ungate_eligible(symbol, family_prefixes=None) -> bool` — True iff a
     non-stale verdict for `symbol` has `verdict == "PASS"`. Default-deny on
     missing. `family_prefixes` optionally narrows the check to verdicts whose
     `family` field equals one of the given prefixes or starts with
     `"<prefix>_"` (e.g. `family_prefixes={"trend"}` matches "trend",
     "trend_rv_filter", "trend_baseline", ... but not "stark_gapfill_long" or
     "meanrev"). Omitting it preserves the original any-family-passes,
     symbol-wide behavior for advisory/read-only callers.
  * `list_verdicts() -> list[VerdictSnapshot]` — all non-stale verdicts.
  * `is_strategy_authorized(symbol) -> tuple[bool, str]` — single source of
     truth for whether a symbol may submit paper orders.  Unifies
     VALIDATION_ONLY_INSTRUMENTS, paper_config.enabled, and gate v2 verdict.

Staleness: any verdict older than `MAX_VERDICT_AGE_DAYS` is treated as
missing. This prevents a one-shot PASS from implicitly authorizing live
trading forever without a fresh re-score.

PRB-02 (2026-07-29): `is_ungate_eligible` was originally symbol-wide only --
"does ANY family have a fresh PASS for this symbol" -- which let an unrelated
strategy's PASS (e.g. a gap-fill scanner) authorize a completely different,
actually-failing strategy (e.g. the live SMA-trend router) for the same
symbol. `family_prefixes` fixes the call site that gates live order routing
(`backtest.signals.generate_instrument_signals`) without changing the
behavior of advisory-only callers (e.g. the weekend research cron) that
intentionally want the broader "is there any validated edge at all for this
symbol" question. See `~/.claude/loops/jarvis-prod-readiness/backlog.json`
PRB-02 for the live-audit finding.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Weekly cron cadence is 7 days — 14 days tolerates one missed run before
# advisory eligibility flips to default-deny.
MAX_VERDICT_AGE_DAYS = 14

# INSUFFICIENT_SAMPLE (Init 2B): the strategy's total OOS trade count is below
# MIN_OOS_TRADES_TOTAL, so the gate refuses rather than certifying on thin
# evidence. It is a non-PASS verdict, so is_ungate_eligible / is_strategy_
# authorized correctly DENY (only "PASS" authorizes) while preserving the
# reason for dashboards — instead of an unknown string making the file
# unreadable and the reason being lost.
_VALID_VERDICTS = frozenset({"PASS", "FAIL", "INSUFFICIENT_SAMPLE"})
_VALID_PASSED_VIA = frozenset({"core", "alt"})
_VALID_CORE_VERDICTS = frozenset({"PASS", "FAIL"})
_VALID_ALT_VERDICTS = frozenset({"PASS", "FAIL", "UNSCORED"})


# Lazy-resolved to avoid circular imports and to let tests monkeypatch.
def _default_verdicts_dir() -> Path:
    """Default verdicts directory: `<engine>/data/gate_v2_verdicts/`."""
    return Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"


@dataclass(slots=True)
class VerdictSnapshot:
    """Read-side mirror of `scripts.gate_v2_orchestrator.VerdictSnapshot`.

    Constructed via `VerdictSnapshot.from_dict(doc)`.  Raises `ValueError`
    on malformed verdict files rather than silently returning wrong answers.

    Intentionally *not* importing the orchestrator's dataclass to avoid
    coupling the read path to the write path — routing code that reads
    verdicts should never have to import heavy numpy/statistics deps.
    """

    symbol: str
    family: str
    rank: int
    verdict: str  # "PASS" | "FAIL"
    passed_via: Optional[str]  # "core" | "alt" | None
    core_verdict: str  # "PASS" | "FAIL"
    alt_verdict: str  # "PASS" | "FAIL" | "UNSCORED"
    n_core_passed: int
    n_alt_passed: int
    created_at: str  # ISO-8601
    aux_freshness: dict
    gate_v2: dict
    # Quantitative gate metrics (pf_ci_lower, mc_95th_dd_pct, dsr, ...) for
    # advisory display. Empty on older verdict files that predate the key.
    gate_v2_metrics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict={self.verdict!r} must be one of {_VALID_VERDICTS}")
        if self.passed_via is not None and self.passed_via not in _VALID_PASSED_VIA:
            raise ValueError(
                f"passed_via={self.passed_via!r} must be one of {_VALID_PASSED_VIA} or None"
            )
        if self.core_verdict not in _VALID_CORE_VERDICTS:
            raise ValueError(
                f"core_verdict={self.core_verdict!r} must be one of {_VALID_CORE_VERDICTS}"
            )
        if self.alt_verdict not in _VALID_ALT_VERDICTS:
            raise ValueError(
                f"alt_verdict={self.alt_verdict!r} must be one of {_VALID_ALT_VERDICTS}"
            )
        if self.n_core_passed < 0:
            raise ValueError(f"n_core_passed={self.n_core_passed} must be >= 0")
        if self.n_alt_passed < 0:
            raise ValueError(f"n_alt_passed={self.n_alt_passed} must be >= 0")
        try:
            datetime.fromisoformat(self.created_at)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"created_at={self.created_at!r} is not a valid ISO datetime") from exc

    @classmethod
    def from_dict(cls, doc: dict) -> "VerdictSnapshot":
        """Construct from a raw verdict JSON dict with schema validation.

        Raises `ValueError` (with the offending field in the message) on any
        missing required key or invalid enum value.  Called by
        `_iter_verdict_files`; errors are caught there and logged as warnings.
        """
        try:
            return cls(
                symbol=doc["symbol"],
                family=doc["family"],
                rank=int(doc["rank"]),
                verdict=doc["verdict"],
                passed_via=doc.get("passed_via"),
                core_verdict=doc.get("core_verdict", "FAIL"),
                alt_verdict=doc.get("alt_verdict", "UNSCORED"),
                n_core_passed=int(doc.get("n_core_passed", 0)),
                n_alt_passed=int(doc.get("n_alt_passed", 0)),
                created_at=doc["created_at"],
                aux_freshness=doc.get("aux_freshness") or {},
                gate_v2=doc.get("gate_v2") or {},
                gate_v2_metrics=doc.get("gate_v2_metrics") or {},
            )
        except KeyError as exc:
            raise ValueError(f"Missing required verdict field: {exc}") from exc

    def age_days(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(tz=timezone.utc)
        created = datetime.fromisoformat(self.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (now - created).total_seconds() / 86400.0

    def is_stale(self, max_age_days: float = MAX_VERDICT_AGE_DAYS) -> bool:
        return self.age_days() > max_age_days


def _iter_verdict_files(verdicts_dir: Optional[Path] = None):
    d = verdicts_dir or _default_verdicts_dir()
    if not d.exists():
        return
    for p in d.glob("*.json"):
        try:
            doc = json.loads(p.read_text())
            yield VerdictSnapshot.from_dict(doc)
        except Exception as exc:
            logger.warning("gate_v2_policy: unreadable verdict file %s: %s", p, exc)


def get_last_verdict(symbol: str, verdicts_dir: Optional[Path] = None) -> Optional[VerdictSnapshot]:
    """Return the newest non-stale verdict for `symbol`, or None."""
    sym_upper = symbol.upper()
    candidates = [
        v
        for v in _iter_verdict_files(verdicts_dir)
        if v.symbol.upper() == sym_upper and not v.is_stale()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v.created_at, reverse=True)
    return candidates[0]


def _family_matches(family: str, family_prefixes: Optional[frozenset]) -> bool:
    """True if `family_prefixes` is unset, or `family` equals one of the given
    prefixes or starts with `"<prefix>_"`.

    Exact-equality plus underscore-boundary prefixing avoids an accidental
    match like prefix "trend" matching an unrelated future family named e.g.
    "trendline_break" — the boundary must be a literal underscore.
    """
    if not family_prefixes:
        return True
    return any(family == p or family.startswith(f"{p}_") for p in family_prefixes)


def is_ungate_eligible(
    symbol: str,
    verdicts_dir: Optional[Path] = None,
    family_prefixes: Optional[frozenset] = None,
) -> bool:
    """Default-deny advisory: `True` iff a non-stale PASS verdict exists
    for `symbol` (optionally restricted to `family_prefixes`).

    Without `family_prefixes` (the original behavior): ANY non-stale PASS
    across ALL families authorizes the symbol. A FAIL in one family (e.g.
    trend_rv_filter) does not negate a PASS in another (e.g. trend) — this
    asks "is there a valid green light for this symbol at all," which is
    appropriate for advisory/read-only callers (e.g. the weekend research
    cron deciding whether a hypothesis is novel).

    With `family_prefixes` set: only verdicts whose `family` matches one of
    the given prefixes (see `_family_matches`) are eligible to authorize.
    Callers that gate real order routing MUST pass the family/families that
    correspond to the strategy code path actually being traded for `symbol`
    — see PRB-02 in the module docstring. A verdict for a different,
    unrelated strategy (different family) must never authorize routing.

    Advisory only — does NOT block any routing decision by itself. Call
    sites may log a warning when this disagrees with the actual routing
    state.
    """
    sym_upper = symbol.upper()
    return any(
        v.verdict == "PASS" and _family_matches(v.family, family_prefixes)
        for v in _iter_verdict_files(verdicts_dir)
        if v.symbol.upper() == sym_upper and not v.is_stale()
    )


def list_verdicts(
    verdicts_dir: Optional[Path] = None,
) -> list[VerdictSnapshot]:
    """Return every non-stale verdict snapshot, newest first."""
    fresh = [v for v in _iter_verdict_files(verdicts_dir) if not v.is_stale()]
    fresh.sort(key=lambda v: v.created_at, reverse=True)
    return fresh


def is_strategy_authorized(
    symbol: str,
    verdicts_dir: Optional[Path] = None,
) -> tuple[bool, str]:
    """Single source of truth: is this symbol authorized to submit paper orders?

    Three necessary conditions checked in order:
    1. Not in VALIDATION_ONLY_INSTRUMENTS (pipeline-level WFE/phase block)
    2. paper_config entry exists with enabled=True (gate v2 PASS has been recorded)
    3. A non-stale gate v2 PASS verdict file exists on disk

    Returns (authorized: bool, reason: str).

    This answers "is trading authorized?" — it does NOT replace runtime safety
    checks (kill switch, lockout, position limits).  Those remain in
    ensure_approval_allowed() and are evaluated independently.
    """
    # Lazy imports avoid circular dependencies at module load time.
    from agents.pipeline import VALIDATION_ONLY_INSTRUMENTS  # noqa: PLC0415
    from backtest.paper_config import PAPER_CONFIGS  # noqa: PLC0415

    sym_upper = symbol.upper()

    # 1. Hard block: VALIDATION_ONLY_INSTRUMENTS (WFE below threshold or phase gate)
    if sym_upper in VALIDATION_ONLY_INSTRUMENTS:
        return (
            False,
            f"{sym_upper} is in VALIDATION_ONLY_INSTRUMENTS — "
            "pipeline runs but no paper orders until WFE >= 0.6 + gate v2 PASS + Tier 3 auth",
        )

    # 2. paper_config.enabled must be True (records that gate v2 approval was granted)
    cfg = PAPER_CONFIGS.get(sym_upper)
    if cfg is None:
        return False, f"{sym_upper} has no entry in PAPER_CONFIGS"
    if not cfg.get("enabled", False):
        return (
            False,
            f"{sym_upper} paper_config.enabled=False "
            "(gate v2 FAIL or not yet validated — see paper_config.py)",
        )

    # 3. Non-stale gate v2 PASS verdict must exist on disk.
    # MES is exempt from this specific check only: Amo's standing directive
    # (2026-06-26, emphatic — "I 10000% never want to disable MES") keeps it
    # active as the primary paper vehicle regardless of gate v2 / re-validation
    # outcome. It still must clear checks 1-2 above like every other symbol —
    # this carve-out narrowly targets the gate-v2-verdict check the directive
    # is actually about, not a blanket bypass of authorization.
    if sym_upper != "MES" and not is_ungate_eligible(sym_upper, verdicts_dir):
        return (
            False,
            f"{sym_upper} has no valid non-stale gate v2 PASS verdict "
            f"(verdicts expire after {MAX_VERDICT_AGE_DAYS} days — re-run gate_v2_orchestrator)",
        )

    return True, "authorized"
