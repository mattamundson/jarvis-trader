"""GepaApplier — writes GEPA target spec to the self-evolution targets dir.

GEPA target specs live at ``/home/mattm/Code/hermes-agent-self-evolution/targets/<slug>.yaml``
(WSL-side). This applier creates that YAML file with a structured target spec
derived from the backlog entry. The actual GEPA optimization run is launched
separately — this applier only stages the spec.

Idempotency: a second ``apply()`` detects the target file already exists and
short-circuits with success.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from datetime import datetime, timezone

import yaml

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

GEPA_TARGETS_DIR = "/home/mattm/Code/hermes-agent-self-evolution/targets"
APPLY_TIMEOUT_S = 30
CHECK_TIMEOUT_S = 10


class GepaApplier(BaseApplier):
    """Applier for UpgradeType="gepa_target" backlog entries."""

    upgrade_type: UpgradeType = "gepa_target"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _slugify_title(self, title: str) -> str:
        """Convert a free-text title to a filesystem-safe slug.

        Example::

            "Recovery hardening for default profile"
            -> "recovery-hardening-for-default-profile"
        """
        s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
        return s[:60] or "untitled-target"

    def _build_spec(self, entry: BacklogEntry) -> dict:
        """Render the YAML body for the target file."""
        return {
            "metadata": {
                "title": entry.title,
                "source_bookmark": entry.source_bookmark_url,
                "source_discord": entry.source_discord_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "leverage_rank": entry.leverage_rank,
            },
            "rationale": entry.rationale,
            "implementation_steps": entry.implementation_steps,
            "dependencies": entry.dependencies,
            "extracted_content": entry.extracted_content,
            "notes": entry.notes,
        }

    @staticmethod
    def _wsl_cmd(bash_cmd: str) -> list[str]:
        """Build the canonical wsl.exe invocation for a bash one-liner."""
        return ["wsl.exe", "-d", "Ubuntu", "-u", "mattm", "-e", "bash", "-lc", bash_cmd]

    # ------------------------------------------------------------------
    # BaseApplier interface
    # ------------------------------------------------------------------
    async def dry_run(self, entry: BacklogEntry) -> str:
        slug = self._slugify_title(entry.title)
        return (
            "# Would write GEPA target spec:\n"
            f"# Path: {GEPA_TARGETS_DIR}/{slug}.yaml\n"
            f"# Title: {entry.title}\n"
            f"# Steps: {len(entry.implementation_steps)}\n"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        slug = self._slugify_title(entry.title)
        target_path = f"{GEPA_TARGETS_DIR}/{slug}.yaml"

        # Idempotency: short-circuit if the target file already exists.
        check_cmd = self._wsl_cmd(
            f"test -f {shlex.quote(target_path)} && echo EXISTS || echo MISSING"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *check_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=CHECK_TIMEOUT_S)
        except (asyncio.TimeoutError, OSError):
            out = b""
        if b"EXISTS" in (out or b""):
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {target_path} already exists",
                post_apply_verification=f"test -f {target_path}",
                rollback_path=f"rm -f {target_path}",
                notes="idempotent skip",
            )

        # Build YAML body from the structured spec.
        spec = self._build_spec(entry)
        yaml_content = yaml.safe_dump(
            spec,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        # Use a heredoc-style delimiter unlikely to appear inside user content.
        # The single-quoted form (<<'DELIM') disables shell expansion so $ and
        # backticks in user content are preserved verbatim.
        delim = "EOF_GEPA_TARGET_" + entry.bookmark_id[-8:]
        if delim in yaml_content:
            delim = "EOF_GEPA_TARGET_" + datetime.now(timezone.utc).strftime("%H%M%S%f")

        write_cmd = (
            f"mkdir -p {shlex.quote(GEPA_TARGETS_DIR)} && "
            f"cat > {shlex.quote(target_path)} <<'{delim}'\n"
            f"{yaml_content}\n"
            f"{delim}\n"
            f"echo OK\n"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._wsl_cmd(write_cmd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=APPLY_TIMEOUT_S)
            success = proc.returncode == 0 and b"OK" in (out or b"")
        except asyncio.TimeoutError:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=f"# write {target_path}",
                post_apply_verification="",
                rollback_path="",
                error="gepa target write timed out",
            )

        output_tail = (out or b"").decode("utf-8", errors="replace")[-300:]
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=success,
            pre_apply_diff=f"wrote {len(yaml_content)} bytes to {target_path}",
            post_apply_verification=f"test -f {target_path} && head -5 {target_path}",
            rollback_path=f"rm -f {target_path}",
            notes=output_tail,
            error=None if success else f"non-zero exit ({proc.returncode}); see notes",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        slug = self._slugify_title(entry.title)
        target_path = f"{GEPA_TARGETS_DIR}/{slug}.yaml"
        cmd = self._wsl_cmd(f"test -s {shlex.quote(target_path)} && echo OK || echo MISSING")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=CHECK_TIMEOUT_S)
        except (asyncio.TimeoutError, OSError):
            return False
        return b"OK" in (out or b"")

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        if not result.rollback_path:
            return False
        cmd = self._wsl_cmd(result.rollback_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(proc.communicate(), timeout=APPLY_TIMEOUT_S)
            return proc.returncode == 0
        except (asyncio.TimeoutError, OSError):
            return False
