"""Appends to ~/.hermes/profiles/<profile>/SOUL.md (or default SOUL).

Idempotent via a per-bookmark marker comment. Always creates a timestamped
backup before mutation; rollback restores from that backup.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from datetime import datetime, timezone
from typing import Optional

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

logger = logging.getLogger(__name__)


SOUL_PATH = {
    "default": "/home/mattm/.hermes/SOUL.md",
    "programmer": "/home/mattm/.hermes/profiles/programmer/SOUL.md",
    "researcher": "/home/mattm/.hermes/profiles/researcher/SOUL.md",
    "designer": "/home/mattm/.hermes/profiles/designer/SOUL.md",
}


_MARKDOWN_FENCE_RE = re.compile(
    r"```(?:markdown|md|soul)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

# Heading that signals a SOUL/persona section worth lifting wholesale.
_SOUL_HEADING_RE = re.compile(
    r"(?im)^(#{1,6}\s+(?:soul|persona|operating\s+contract|system\s+prompt)\b.*)$",
)

# Phrasing introducing a block that should be appended ("Append this to SOUL.md").
_APPEND_INTRO_RE = re.compile(
    r"(?i)(append(?:\s+(?:this|the\s+following))?\s+to\s+(?:the\s+)?SOUL\.md"
    r"|add(?:\s+(?:this|the\s+following))?\s+to\s+(?:the\s+)?SOUL\.md"
    r"|use\s+this\s+(?:persona|template)"
    r"|adopt\s+this\s+(?:persona|template))",
)

# Persona-like prose markers — detect a paragraph that reads as a system prompt
# ("you are an X who Y").
_PERSONA_PROSE_RE = re.compile(
    r"(?i)\byou\s+are\s+(?:an?|the)\b.{20,}",
)


class SoulPatcher(BaseApplier):
    """Appends a proposed section to one of the 4 profile SOUL.md files."""

    upgrade_type: UpgradeType = "soul_template"

    # ----- Helpers --------------------------------------------------------

    def _determine_profile(self, entry: BacklogEntry) -> str:
        """Route to programmer/researcher/designer/default based on entry text.

        Scans ALL textual fields (title, rationale, notes, extracted_content,
        every implementation step) — previously notes/title/rationale/steps
        only, which missed entries that named the profile only in
        extracted_content.
        """
        haystack = " ".join(
            [
                entry.notes or "",
                entry.title or "",
                entry.rationale or "",
                entry.extracted_content or "",
                " ".join(entry.implementation_steps or []),
            ]
        ).lower()
        for profile in ("programmer", "researcher", "designer"):
            if profile in haystack:
                return profile
        return "default"

    def _extract_soul_addition(self, entry: BacklogEntry) -> Optional[str]:
        """Pull the proposed SOUL section from any textual field.

        Resolution order:
            1. Fenced ``` markdown blocks (any field)
            2. ``# Soul`` / ``## Persona`` / ``# Operating contract`` headed
               section + following content (any field)
            3. "Append this to SOUL.md" / "Adopt this persona" intro → capture
               the following content (next paragraph or remainder)
            4. Persona-like paragraph ("you are a <role>, your job is to …")
            5. Generic section header + body (existing fallback)
            6. Long extracted_content prose (existing fallback)
        """
        sources = [
            entry.extracted_content or "",
            *(entry.implementation_steps or []),
            entry.notes or "",
            entry.rationale or "",
        ]

        # 1. Fenced markdown blocks anywhere.
        for source in sources:
            m = _MARKDOWN_FENCE_RE.search(source)
            if m:
                block = m.group(1).strip()
                if block:
                    return block

        # 2. SOUL/Persona headed section — capture from the heading up to next
        #    same-or-higher-level heading (or end of source).
        for source in sources:
            m = _SOUL_HEADING_RE.search(source)
            if m:
                start = m.start()
                # Find next heading of any level after this one (skip first line).
                tail = source[m.end() :]
                next_heading = re.search(r"\n#{1,6}\s+\S", tail)
                end = m.end() + next_heading.start() if next_heading else len(source)
                block = source[start:end].strip()
                if len(block) >= 20:
                    return block

        # 3. "Append this to SOUL.md" / "Adopt this persona" intro phrase →
        #    grab whatever follows that intro in the same source.
        for source in sources:
            m = _APPEND_INTRO_RE.search(source)
            if m:
                tail = source[m.end() :].strip()
                # Strip leading colon / dash / quote characters.
                tail = tail.lstrip(":-—–\"' \n\t")
                if len(tail) >= 20:
                    # Cap at the next blank-line paragraph break to keep things tight.
                    para_end = tail.find("\n\n")
                    block = (tail[:para_end] if para_end > 0 else tail).strip()
                    if len(block) >= 20:
                        return block

        # 4. Persona-like prose paragraph.
        for source in sources:
            m = _PERSONA_PROSE_RE.search(source)
            if m:
                # Capture from the match start to the next blank-line break.
                tail = source[m.start() :]
                para_end = tail.find("\n\n")
                block = (tail[:para_end] if para_end > 0 else tail).strip()
                if len(block) >= 20:
                    return block

        # 5. Generic section header + body (existing fallback).
        for source in sources:
            m = re.search(
                r"(^|\n)(#{1,6}\s+.+\n(?:.+\n?){1,200})",
                source,
            )
            if m:
                block = m.group(2).strip()
                if len(block) >= 20:
                    return block

        # 6. Long extracted_content prose (existing fallback).
        extracted = (entry.extracted_content or "").strip()
        if len(extracted) >= 40:
            return extracted

        return None

    @staticmethod
    def _marker(bookmark_id: str) -> str:
        return f"<!-- hermes-upgrade:{bookmark_id} -->"

    async def _run_wsl(self, cmd_str: str, timeout: float = 30) -> tuple[int, str]:
        """Run a bash command inside WSL Ubuntu as user mattm. Returns (rc, stdout)."""
        import os

        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "WSLENV": "PYTHONIOENCODING/u",
        }
        try:
            proc = await asyncio.create_subprocess_exec(
                "wsl.exe",
                "-d",
                "Ubuntu",
                "-u",
                "mattm",
                "-e",
                "bash",
                "-lc",
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("WSL command timed out: %s", cmd_str[:120])
            return (-1, "")
        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        return (proc.returncode if proc.returncode is not None else -1, text)

    # ----- Lifecycle ------------------------------------------------------

    async def dry_run(self, entry: BacklogEntry) -> str:
        profile = self._determine_profile(entry)
        addition = self._extract_soul_addition(entry)
        if not addition:
            return f"ERROR: could not extract SOUL addition from {entry.bookmark_id}"
        return (
            f"# Would append to SOUL.md for profile={profile}\n"
            f"# Path: {SOUL_PATH[profile]}\n"
            f"# Backup: {SOUL_PATH[profile]}.bak.<UTC-ts>\n"
            f"# Marker: {self._marker(entry.bookmark_id)}\n"
            f"# ---NEW SECTION---\n{addition[:800]}\n"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        profile = self._determine_profile(entry)
        addition = self._extract_soul_addition(entry)
        if not addition:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error="could not extract SOUL addition",
            )

        soul_path = SOUL_PATH[profile]
        marker = self._marker(entry.bookmark_id)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{soul_path}.bak.{ts}"

        # Idempotency: skip if marker already present.
        check_cmd = (
            f"if [ -f {shlex.quote(soul_path)} ] && "
            f"grep -qF {shlex.quote(marker)} {shlex.quote(soul_path)}; then "
            f"echo EXISTS; else echo MISSING; fi"
        )
        rc, out = await self._run_wsl(check_cmd, timeout=15)
        if rc == 0 and "EXISTS" in out:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# marker {marker} already present in {soul_path}",
                post_apply_verification=(
                    f"grep -qF {shlex.quote(marker)} {shlex.quote(soul_path)}"
                ),
                rollback_path="",
                notes="idempotent skip",
            )

        # Build append payload via a single shell pipeline (mkdir → backup → append).
        # Use a single-quoted heredoc to disable variable expansion in `addition`.
        # Replace any literal EOF_HERMES_SOUL token to avoid heredoc collision.
        safe_addition = addition.replace("EOF_HERMES_SOUL", "EOF_HERMES_SOUL_x")
        timestamp_line = f"<!-- applied: {datetime.now(timezone.utc).isoformat()} -->"

        # The body we append: blank line, marker, timestamp comment, then the addition.
        body = f"\n\n{marker}\n{timestamp_line}\n{safe_addition}\n"

        # Compose the script. mkdir -p the parent in case profile dir is missing.
        # `touch` ensures the file exists (so `cp` for backup doesn't fail on a
        # fresh profile that has never had a SOUL.md).
        cmd_str = (
            f"set -e; "
            f"mkdir -p $(dirname {shlex.quote(soul_path)}); "
            f"touch {shlex.quote(soul_path)}; "
            f"cp {shlex.quote(soul_path)} {shlex.quote(backup_path)}; "
            f"cat >> {shlex.quote(soul_path)} <<'EOF_HERMES_SOUL'"
            f"{body}"
            f"EOF_HERMES_SOUL"
        )

        rc, out = await self._run_wsl(cmd_str, timeout=30)
        success = rc == 0
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=success,
            pre_apply_diff=(
                f"# Append marker {marker} + {len(addition)} chars to {soul_path}\n"
                f"# Backup: {backup_path}\n"
            ),
            post_apply_verification=(f"grep -qF {shlex.quote(marker)} {shlex.quote(soul_path)}"),
            rollback_path=backup_path,
            notes=f"output: {out[-500:]}" if out else "",
            error=None if success else f"append exit={rc}",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        profile = self._determine_profile(entry)
        marker = self._marker(entry.bookmark_id)
        soul_path = SOUL_PATH[profile]
        cmd_str = (
            f"grep -qF {shlex.quote(marker)} {shlex.quote(soul_path)} "
            f"&& echo OK || echo MISSING"
        )
        rc, out = await self._run_wsl(cmd_str, timeout=15)
        if rc != 0:
            return False
        return "OK" in out

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        """Restore SOUL.md from the timestamped backup recorded in result."""
        if not result.rollback_path:
            return False
        profile = self._determine_profile(entry)
        soul_path = SOUL_PATH[profile]
        backup_path = result.rollback_path
        cmd_str = (
            f"if [ -f {shlex.quote(backup_path)} ]; then "
            f"cp {shlex.quote(backup_path)} {shlex.quote(soul_path)} && echo OK; "
            f"else echo MISSING_BACKUP; fi"
        )
        rc, out = await self._run_wsl(cmd_str, timeout=15)
        return rc == 0 and "OK" in out
