"""Registers a Hermes cron via `hermes cron add` (WSL-side).

Parses cron spec (name, schedule, prompt, profile) from a BacklogEntry's
implementation_steps. Idempotent: skips if a cron with the same name is
already registered for the target profile.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Optional

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

logger = logging.getLogger(__name__)


_VALID_PROFILES = ("default", "programmer", "researcher", "designer")

# Cron-shaped schedule (5 fields). Catches `0 8 * * *`, `*/15 * * * *`, etc.
_CRON_RE = re.compile(
    r"(?:^|\s)((?:\S+\s+){4}\S+)(?:\s|$)",
)

# Natural-language schedule fallback (e.g. "every day 8am Central", "weekly Mon 9am").
_NL_SCHEDULE_RE = re.compile(
    r"(?i)\b(every (?:day|hour|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+at\s+\S+(?:\s+(?:am|pm))?)?(?:\s+\S+)?"
    r"|daily(?:\s+at\s+\S+)?"
    r"|weekly(?:\s+\S+)?"
    r"|hourly"
    r"|nightly(?:\s+at\s+\S+)?)",
)


def _extract_quoted_after(text: str, token: str) -> Optional[str]:
    """Extract the next single- or double-quoted string after `token` in `text`."""
    idx = text.find(token)
    if idx < 0:
        return None
    tail = text[idx + len(token) :]
    m = re.match(r"\s*(['\"])(.*?)\1", tail, re.DOTALL)
    if m:
        return m.group(2)
    # Fall back to next whitespace-delimited token (unquoted).
    m = re.match(r"\s*(\S+)", tail)
    return m.group(1) if m else None


class CronRegister(BaseApplier):
    """Registers a Hermes cron via `hermes cron add` (WSL-side)."""

    upgrade_type: UpgradeType = "cron_pattern"

    def _extract_cron_spec(self, entry: BacklogEntry) -> Optional[dict]:
        """Parse a cron spec out of implementation_steps / extracted_content.

        Returns a dict with keys: name, schedule, prompt, profile. Returns None
        if any required field cannot be determined.
        """
        steps = entry.implementation_steps or []
        haystack_parts = list(steps) + [entry.extracted_content or "", entry.notes or ""]
        haystack = "\n".join(p for p in haystack_parts if p)

        # 1. Try to find a `hermes cron add ...` invocation we can parse.
        for step in steps:
            if "hermes cron add" not in step:
                continue
            name = _extract_quoted_after(step, "--name")
            schedule = _extract_quoted_after(step, "--schedule")
            prompt = _extract_quoted_after(step, "--prompt")
            profile = _extract_quoted_after(step, "--profile") or self._infer_profile(haystack)
            if name and schedule and prompt:
                return {
                    "name": name,
                    "schedule": schedule,
                    "prompt": prompt,
                    "profile": profile if profile in _VALID_PROFILES else "default",
                }

        # 2. Heuristic fallback: find a schedule shape + a prompt body.
        schedule = self._find_schedule(haystack)
        if not schedule:
            return None

        prompt = self._find_prompt(steps, entry.extracted_content or "")
        if not prompt:
            return None

        name = self._derive_name(entry, prompt)
        if not name:
            return None

        profile = self._infer_profile(haystack)
        return {
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "profile": profile if profile in _VALID_PROFILES else "default",
        }

    def _find_schedule(self, text: str) -> Optional[str]:
        """Find a cron-shaped or natural-language schedule string."""
        # Prefer real cron expressions.
        for line in text.splitlines():
            stripped = line.strip()
            # Skip command-shaped lines that contain the cron tool itself.
            if stripped.startswith("#") or not stripped:
                continue
            # Strip a `Schedule:` / `Cron:` label prefix if present.
            label = re.match(r"(?i)(?:schedule|cron|when)\s*[:=]\s*", stripped)
            candidate_line = stripped[label.end() :] if label else stripped
            tokens = candidate_line.split()
            if len(tokens) == 5 and all(self._is_cron_token(t) for t in tokens):
                return candidate_line
        m = _CRON_RE.search(text)
        if m:
            candidate = m.group(1).strip()
            if all(self._is_cron_token(t) for t in candidate.split()):
                return candidate
        # Fall back to natural-language schedule.
        m = _NL_SCHEDULE_RE.search(text)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _is_cron_token(token: str) -> bool:
        """True if `token` looks like a single field in a cron expression.

        Accepts numeric fields (`0`, `*/15`, `1-5`), star, and 3-letter
        day/month abbreviations (`MON`, `JAN`) — alone or with a range.
        """
        return bool(re.fullmatch(r"(?:[\d\*\-,/]+(?:[A-Z]{3})?|[A-Z]{3}(?:-[A-Z]{3})?)", token))

    def _find_prompt(self, steps: list[str], extracted: str) -> Optional[str]:
        """Find the natural-language instruction Hermes should run."""
        # Look for an explicit `prompt:` / `Prompt:` line.
        for source in [*steps, extracted]:
            for line in source.splitlines():
                m = re.match(r"\s*(?:prompt|instruction)\s*[:=]\s*(.+)$", line, re.IGNORECASE)
                if m:
                    return m.group(1).strip().strip("\"'")
        # Look for a fenced quote inside the source body.
        for source in [extracted, *steps]:
            m = re.search(r"['\"]([^'\"\n]{20,400})['\"]", source)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _derive_name(entry: BacklogEntry, prompt: str) -> Optional[str]:
        """Derive a slug for the cron name from the entry title or prompt."""
        for candidate in (entry.title, prompt):
            if not candidate:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
            if slug:
                # Cap length to keep CLI invocations sane.
                return slug[:60]
        return None

    @staticmethod
    def _infer_profile(text: str) -> str:
        """Infer the target profile from haystack text. Defaults to 'default'."""
        lower = text.lower()
        for p in ("programmer", "researcher", "designer"):
            if p in lower:
                return p
        return "default"

    # ----- Lifecycle ------------------------------------------------------

    async def dry_run(self, entry: BacklogEntry) -> str:
        spec = self._extract_cron_spec(entry)
        if not spec:
            return f"ERROR: could not extract cron spec from {entry.bookmark_id}"
        return (
            f"# Would register Hermes cron (profile={spec.get('profile', 'default')}):\n"
            f"hermes cron add --name '{spec['name']}' --schedule '{spec['schedule']}' \\\n"
            f"  --prompt '{spec['prompt']}'\n"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        spec = self._extract_cron_spec(entry)
        if not spec:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error="could not parse cron spec",
            )

        profile = spec.get("profile", "default")

        # Idempotency check: list current crons; skip if name already registered.
        existing = await self._list_existing_crons(profile)
        if any(spec["name"] in line for line in existing):
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {spec['name']} already registered",
                post_apply_verification=f"hermes cron list | grep -F {spec['name']}",
                rollback_path=f"hermes cron remove {shlex.quote(spec['name'])}",
                notes="idempotent skip",
            )

        cmd_str = (
            f"hermes cron add --name {shlex.quote(spec['name'])} "
            f"--schedule {shlex.quote(spec['schedule'])} "
            f"--prompt {shlex.quote(spec['prompt'])}"
        )
        if profile and profile != "default":
            cmd_str = f"HERMES_PROFILE={shlex.quote(profile)} {cmd_str}"

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
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=cmd_str,
                post_apply_verification="",
                rollback_path="",
                error="cron add timed out after 60s",
            )

        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        success = proc.returncode == 0

        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=success,
            pre_apply_diff=cmd_str,
            post_apply_verification=f"hermes cron list | grep -F {shlex.quote(spec['name'])}",
            rollback_path=f"hermes cron remove {shlex.quote(spec['name'])}",
            notes=f"output: {output[-500:]}",
            error=None if success else f"hermes cron add exit={proc.returncode}",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        spec = self._extract_cron_spec(entry)
        if not spec:
            return False
        existing = await self._list_existing_crons(spec.get("profile", "default"))
        return any(spec["name"] in line for line in existing)

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        spec = self._extract_cron_spec(entry)
        if not spec:
            return False
        profile = spec.get("profile", "default")
        cmd_str = f"hermes cron remove {shlex.quote(spec['name'])} 2>&1 || true"
        if profile and profile != "default":
            cmd_str = f"HERMES_PROFILE={shlex.quote(profile)} {cmd_str}"
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
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("cron rollback timed out for %s", entry.bookmark_id)
            return False
        return True

    async def _list_existing_crons(self, profile: str = "default") -> list[str]:
        """Return current cron list output (one entry per line). Empty on failure."""
        prefix = f"HERMES_PROFILE={shlex.quote(profile)} " if profile != "default" else ""
        cmd_str = f"{prefix}hermes cron list 2>&1 || echo __HERMES_ERR__"
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
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("hermes cron list timed out")
            return []
        if proc.returncode != 0:
            return []
        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        if "__HERMES_ERR__" in text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]
