"""Phase 3 orchestrator: loads backlog, dispatches to per-type appliers, records to applied-log.

Safety rails:
- Per-item human approval (default) — pass --auto-approve-low-risk only for tier_1 low-risk.
- Pre-apply diff shown to user (or written to apply-preview.md).
- Post-apply verification required before marking applied.
- Rollback path always recorded.
- Idempotent — re-running on an already-applied entry is a no-op.
- One commit per applied entry to the appropriate target (Hermes config, claude.json, etc.).
- Audit log at ~/.hermes/upgrade/applied.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows cp1252 stdout crashes on Unicode chars like → (U+2192) found in
# soul_template diff previews. Force UTF-8 before any print() runs.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from .appliers.base import BaseApplier
from .models import ApplyResult, BacklogEntry, UpgradeType

logger = logging.getLogger(__name__)


def _get_applier(upgrade_type: UpgradeType) -> BaseApplier:
    """Lazy-import the per-type applier so missing modules don't break import."""
    if upgrade_type == "skill":
        from .appliers.skill_installer import SkillInstaller

        return SkillInstaller()
    if upgrade_type == "mcp_server":
        from .appliers.mcp_adder import McpAdder

        return McpAdder()
    if upgrade_type == "cron_pattern":
        from .appliers.cron_register import CronRegister

        return CronRegister()
    if upgrade_type == "soul_template":
        from .appliers.soul_patcher import SoulPatcher

        return SoulPatcher()
    if upgrade_type == "library":
        from .appliers.library_integrator import LibraryIntegrator

        return LibraryIntegrator()
    if upgrade_type == "config_improvement":
        from .appliers.config_patcher import ConfigPatcher

        return ConfigPatcher()
    if upgrade_type == "gepa_target":
        from .appliers.gepa_applier import GepaApplier

        return GepaApplier()
    raise ValueError(f"No applier registered for upgrade_type={upgrade_type}")


def load_backlog(jsonl_path: Path) -> list[BacklogEntry]:
    """Load the backlog from JSONL produced by Phase 2."""
    entries: list[BacklogEntry] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            entries.append(BacklogEntry(**data))
    return entries


def save_backlog(entries: list[BacklogEntry], jsonl_path: Path) -> None:
    """Persist updated backlog (with new apply_status) back to JSONL."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e.model_dump(mode="json"), default=str) + "\n")


def append_applied_log(result: ApplyResult, log_path: Path) -> None:
    """Append an immutable audit entry to applied.jsonl."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result.model_dump(mode="json"),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def apply_one(
    entry: BacklogEntry,
    *,
    dry_run_only: bool = False,
    auto_approve: bool = False,
) -> ApplyResult:
    """Run the full apply lifecycle for one entry.

    Returns an ApplyResult capturing pre-apply diff, post-apply verification,
    rollback path, and notes. Caller is responsible for persisting state.
    """
    # Idempotent short-circuit: already applied
    if entry.apply_status == "applied":
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff="<already applied>",
            post_apply_verification="<idempotent skip>",
            rollback_path=entry.rollback_path,
            notes="Already applied — skipped",
        )

    # Explicit user-skip terminal state
    if entry.apply_status == "skipped":
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=False,
            pre_apply_diff="",
            post_apply_verification="",
            rollback_path="",
            notes="Previously skipped by user",
        )

    applier = _get_applier(entry.upgrade_type)

    # Step 1: dry-run preview
    diff = await applier.dry_run(entry)
    print(f"\n=== Applying [{entry.bookmark_id}] {entry.title} ===")
    print(
        f"Type: {entry.upgrade_type}  "
        f"Tier: {entry.tier}  "
        f"Leverage: {entry.leverage_rank}/5  "
        f"Risk: {entry.risk}"
    )
    print(f"Pre-apply diff/command preview:\n{diff}\n")

    if dry_run_only:
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff=diff,
            post_apply_verification="<dry-run only>",
            rollback_path="",
            notes="Dry-run mode — no changes applied",
        )

    # Step 2: gate behind explicit approval unless auto-approved
    if not auto_approve:
        try:
            ans = input(f"Apply [{entry.bookmark_id}]? [y/N/q]: ").strip().lower()
        except EOFError:
            # No interactive TTY (scheduled/headless run) and this entry is not
            # auto-approvable. Do NOT treat as an explicit user skip — that writes
            # a terminal "skipped" state and permanently hides the entry from a
            # later interactive/authorized run. Defer instead: leave it retryable.
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=diff,
                post_apply_verification="",
                rollback_path="",
                notes="Deferred — no interactive TTY for approval (left pending)",
                deferred=True,
            )
        if ans == "q":
            print("Quitting.")
            sys.exit(0)
        if ans != "y":
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=diff,
                post_apply_verification="",
                rollback_path="",
                notes="User skipped",
            )

    # Step 3: apply
    result = await applier.apply(entry)
    if not result.success:
        return result

    # Step 4: verify
    ok = await applier.verify(entry, result)
    if not ok:
        result.success = False
        result.notes = (result.notes or "") + " — verification failed; consider rollback"

    return result


async def apply_many(
    entries: list[BacklogEntry],
    *,
    backlog_path: Path,
    applied_log_path: Path,
    tier_filter: str | None = None,
    upgrade_type_filter: str | None = None,
    bookmark_id_filter: str | None = None,
    dry_run_only: bool = False,
    auto_approve_low_risk: bool = False,
) -> list[ApplyResult]:
    """Apply many entries with filters. Updates backlog state + applied-log."""
    results: list[ApplyResult] = []
    for entry in entries:
        if tier_filter and entry.tier != tier_filter:
            continue
        if upgrade_type_filter and entry.upgrade_type != upgrade_type_filter:
            continue
        if bookmark_id_filter and entry.bookmark_id != bookmark_id_filter:
            continue
        if not entry.applicable_or_pending():
            continue

        # Per-entry auto-approve eligibility
        local_auto = auto_approve_low_risk and entry.tier == "tier_1" and entry.risk == "low"

        try:
            result = await apply_one(
                entry,
                dry_run_only=dry_run_only,
                auto_approve=local_auto,
            )
        except ValueError as exc:
            # No applier registered for this upgrade_type (e.g., a future / unknown type).
            # Graceful degrade — don't crash the whole batch.
            logger.warning(
                "no applier for upgrade_type=%s on %s: %s",
                entry.upgrade_type,
                entry.bookmark_id,
                exc,
            )
            result = ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                notes=f"no-applier-for-type: {entry.upgrade_type}",
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — surface unexpected applier failures
            logger.exception("apply_one raised for %s", entry.bookmark_id)
            result = ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                notes="apply_one raised",
                error=f"{type(exc).__name__}: {exc}",
            )

        results.append(result)

        # Headless deferral: no TTY to approve and not auto-approvable. Leave the
        # entry in its current retryable state (pending/failed) and do NOT append
        # to the applied-log — it was neither applied nor skipped.
        if result.deferred:
            logger.info(
                "deferred (no TTY) %s — left %s for a later interactive run",
                entry.bookmark_id,
                entry.apply_status,
            )
            continue

        # Update entry state based on result
        notes_lc = (result.notes or "").lower()
        if result.success:
            entry.apply_status = "applied"
            entry.apply_timestamp = datetime.now(timezone.utc)
            entry.apply_outcome = result.notes
            entry.rollback_path = result.rollback_path
        elif "skipped" in notes_lc:
            entry.apply_status = "skipped"
            entry.apply_outcome = result.notes
        else:
            entry.apply_status = "failed"
            entry.apply_outcome = (result.error or "") + " " + (result.notes or "")

        if not dry_run_only:
            append_applied_log(result, applied_log_path)
            save_backlog(entries, backlog_path)

    return results


def _default_dir() -> Path:
    if os.name == "nt":
        return Path(r"C:\Users\mattm\.hermes\upgrade")
    return Path(os.path.expanduser("~/.hermes/upgrade"))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Phase 3 orchestrator for the Hermes self-improvement loop."
    )
    p.add_argument("--backlog", default=None, help="Path to backlog.jsonl")
    p.add_argument("--tier", choices=["tier_1", "tier_2", "tier_3"], default=None)
    p.add_argument("--upgrade-type", default=None)
    p.add_argument("--bookmark-id", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--auto-approve-low-risk",
        action="store_true",
        help="Auto-apply tier_1+low_risk entries without prompting",
    )
    args = p.parse_args()

    default_dir = _default_dir()
    backlog_path = Path(args.backlog) if args.backlog else default_dir / "backlog.jsonl"
    applied_log = default_dir / "applied.jsonl"

    if not backlog_path.exists():
        print(
            f"No backlog at {backlog_path}. "
            "Run Phase 1+2 first: python -m discord.hermes_upgrade"
        )
        sys.exit(1)

    entries = load_backlog(backlog_path)
    print(f"Loaded {len(entries)} entries from {backlog_path}")

    results = asyncio.run(
        apply_many(
            entries,
            tier_filter=args.tier,
            upgrade_type_filter=args.upgrade_type,
            bookmark_id_filter=args.bookmark_id,
            dry_run_only=args.dry_run,
            auto_approve_low_risk=args.auto_approve_low_risk,
            backlog_path=backlog_path,
            applied_log_path=applied_log,
        )
    )

    successes = sum(1 for r in results if r.success)
    print(f"\n=== Applied {successes} / {len(results)} ===")


if __name__ == "__main__":
    main()
