"""BaseApplier ABC — contract for per-type appliers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ApplyResult, BacklogEntry, UpgradeType


class BaseApplier(ABC):
    """Per-type applier. Each subclass handles one UpgradeType.

    Lifecycle:
        applier.dry_run(entry)         -> human-readable diff/command preview
        amo_approves                    -> caller invokes apply()
        applier.apply(entry)            -> ApplyResult with rollback_path
        applier.verify(entry, result)   -> bool (post-apply check)
        applier.rollback(entry, result) -> bool (if needed)

    Idempotency: apply() MUST be safe to call twice; the second call should
    detect the prior state and return success without re-doing work.
    """

    upgrade_type: UpgradeType  # subclass sets this

    @abstractmethod
    async def dry_run(self, entry: BacklogEntry) -> str:
        """Render the proposed change as a human-readable diff or command sequence.

        Should NOT mutate any state. Used to populate the "Apply this?" prompt
        shown to Amo.
        """
        ...

    @abstractmethod
    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        """Execute the change. Must be idempotent.

        Returns an ApplyResult with success flag, rollback_path, and notes.
        The orchestrator records this and updates the backlog entry.
        """
        ...

    @abstractmethod
    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        """Post-apply verification. Returns True iff the change took effect.

        For a skill install: check `hermes skill list | grep <slug>`.
        For an MCP add: check `~/.hermes/config.yaml` has the new entry.
        For a cron register: check `hermes cron list`.
        """
        ...

    @abstractmethod
    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        """Revert the change. Returns True iff rollback succeeded."""
        ...
