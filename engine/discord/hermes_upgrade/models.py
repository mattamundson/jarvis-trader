"""Pydantic schemas for the Hermes self-improvement pipeline.

Shared contracts between scanner, classifier, backlog, and the per-type
appliers. Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums (Literal for static-typing + Pydantic validation)
# ---------------------------------------------------------------------------

UpgradeType = Literal[
    "skill",  # new Hermes skill to install (community hub or git URL)
    "mcp_server",  # new MCP server to wire into ~/.hermes/config.yaml or ~/.claude.json
    "cron_pattern",  # a cron design worth registering (researcher digest, weekly sync, etc.)
    "soul_template",  # a SOUL.md pattern worth adapting for one of the 4 profiles
    "library",  # a Python/JS library worth integrating into Hermes/GEPA venvs
    "config_improvement",  # a tunable in ~/.hermes/config.yaml worth changing
    "gepa_target",  # a skill recommended for GEPA optimization run
    "none",  # classifier determined not applicable to Hermes
]

Tier = Literal[
    "tier_1",  # high leverage, low risk — do first
    "tier_2",  # high leverage, medium risk — needs config/cred decisions
    "tier_3",  # speculative or experimental
    "defer",  # already applied / superseded / blocked
]

ApplyStatus = Literal["pending", "applied", "skipped", "failed", "rolled_back"]

Risk = Literal["low", "med", "high"]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    """A bookmark surfaced by the scanner as potentially Hermes-applicable.

    Output of `scanner.scan_for_candidates()`. Pre-LLM heuristic; cheap signal.
    """

    model_config = ConfigDict(populate_by_name=True)

    bookmark_id: str
    analysis_id: int
    url: str
    summary: str
    structured_json: str  # raw JSON string from discord_analyses.structured_json
    topics: list[str] = Field(default_factory=list)
    has_action_item: bool = False
    source_kind: str = "url"
    artifact_type: str = "url"
    posted_at: Optional[str] = None
    score: float = 0.0  # scanner's heuristic interest score 0.0-1.0


class ClassifiedUpgrade(BaseModel):
    """A candidate that has been LLM-classified into structured upgrade intent.

    Output of `classifier.classify_batch()`. One LLM call per candidate.
    """

    model_config = ConfigDict(populate_by_name=True)

    bookmark_id: str
    applicable: bool
    upgrade_type: UpgradeType = "none"
    title: str = (
        ""  # short human-readable headline (e.g., "Install autonomous-ai-agents/claude-code")
    )
    rationale: str = ""  # 1-2 sentence why this is worth doing
    implementation_steps: list[str] = Field(default_factory=list)  # concrete shell/yaml/cli steps
    leverage_rank: int = 1  # 1-5, higher = more impact for Amo's current setup
    risk: Risk = "low"
    dependencies: list[str] = Field(default_factory=list)  # what must be true before applying
    estimated_cost_usd: float = 0.0  # ongoing or one-shot cost
    extracted_content: str = ""  # the relevant quote/snippet from the source bookmark
    notes: str = ""  # any caveats / amo-only steps / etc.


class BacklogEntry(BaseModel):
    """A classified upgrade with tier + source + apply state.

    Written to `~/.hermes/upgrade/backlog.md` and to a sidecar JSONL log.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Candidate identity
    bookmark_id: str
    source_bookmark_url: str  # the original bookmark URL (e.g., x.com link)
    source_discord_url: str  # discord.com/channels/... canonical link
    source_vault_path: str  # path to the vault page

    # Classification
    upgrade_type: UpgradeType
    title: str
    rationale: str
    implementation_steps: list[str]
    leverage_rank: int
    risk: Risk
    dependencies: list[str]
    estimated_cost_usd: float
    extracted_content: str
    notes: str

    # Triage
    tier: Tier

    # Apply state
    apply_status: ApplyStatus = "pending"
    apply_timestamp: Optional[datetime] = None
    apply_outcome: str = ""
    rollback_path: str = ""

    def applicable_or_pending(self) -> bool:
        """True iff this entry is eligible for an apply attempt.

        Used by the Phase 3 orchestrator to skip entries already in a terminal
        success state ("applied") or explicitly opted-out ("skipped",
        "rolled_back"). "failed" entries are re-eligible because the prior
        failure may have been transient.
        """
        return self.apply_status in ("pending", "failed")


class ApplyResult(BaseModel):
    """Result of running an Applier against a BacklogEntry."""

    model_config = ConfigDict(populate_by_name=True)

    bookmark_id: str
    success: bool
    pre_apply_diff: str  # rendered diff or command sequence — shown to Amo before apply
    post_apply_verification: str  # what we checked after (command + output)
    rollback_path: str  # how to undo (script path or git revert hash or rm command)
    notes: str = ""
    error: Optional[str] = None
    # True when no interactive TTY was available to approve and the entry was not
    # auto-approvable — a headless deferral, NOT a user skip. The orchestrator must
    # leave such entries retryable (pending) rather than writing a terminal state.
    deferred: bool = False
