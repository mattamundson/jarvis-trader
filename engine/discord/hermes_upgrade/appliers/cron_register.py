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
# Note: longer day variants must precede shorter ones in alternation (weekday > week,
# monday > mon) because regex alternation is greedy left-to-right.
_NL_SCHEDULE_RE = re.compile(
    r"(?i)\b(every (?:weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|day|hour|week)"
    r"(?:s)?"
    r"(?:\s+at)?(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|daily(?:\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|weekly(?:\s+\S+)?"
    r"|hourly"
    r"|nightly(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|every\s+\d+\s+(?:minute|min|hour|day|week)s?)",
)

# "every N minutes/hours" → cron `*/N * * * *` / `0 */N * * *`.
_EVERY_N_RE = re.compile(r"(?i)\bevery\s+(\d+)\s+(minute|min|hour|day|week)s?\b")

# Day-of-week to cron index (0=Sun … 6=Sat).
_DOW = {
    "sunday": 0,
    "sun": 0,
    "monday": 1,
    "mon": 1,
    "tuesday": 2,
    "tue": 2,
    "tues": 2,
    "wednesday": 3,
    "wed": 3,
    "thursday": 4,
    "thu": 4,
    "thurs": 4,
    "friday": 5,
    "fri": 5,
    "saturday": 6,
    "sat": 6,
}

# "every day at 8am" / "daily 6am" / "every weekday at 8am".
_DAILY_AT_RE = re.compile(
    r"(?i)\b(?:every\s+(?:week)?day|daily|nightly)"
    r"(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
)

# "weekly on Monday at 10am" / "every Sunday 7pm".
_WEEKLY_DOW_RE = re.compile(
    r"(?i)\b(?:weekly\s+on|every)\s+"
    r"(sunday|sun|monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thurs|friday|fri|saturday|sat)"
    r"s?"
    r"(?:\s+at)?\s*(\d{1,2})?(?::(\d{2}))?\s*(am|pm)?\b",
)


def _phrase_to_cron(phrase: str) -> str | None:
    """Convert common natural-language schedule phrases to cron form.

    Returns None if the phrase isn't recognized — caller can fall back to
    leaving the phrase as-is and letting Hermes parse it.
    """
    text = phrase.strip()

    # "every N minute/hour/day/week" → standard cron.
    m = _EVERY_N_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("minute", "min"):
            return f"*/{n} * * * *"
        if unit == "hour":
            return f"0 */{n} * * *"
        if unit == "day":
            return f"0 0 */{n} * *"
        if unit == "week":
            # cron has no /week field — use `0 0 * * 0` for weekly Sunday default.
            return "0 0 * * 0"

    # "weekly on <dow> at <H>(am|pm)" / "every <dow> <H>am".
    m = _WEEKLY_DOW_RE.search(text)
    if m:
        dow_word = m.group(1).lower()
        dow_idx = _DOW.get(dow_word)
        if dow_idx is not None:
            hour = int(m.group(2)) if m.group(2) else 0
            minute = int(m.group(3)) if m.group(3) else 0
            ampm = (m.group(4) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return f"{minute} {hour} * * {dow_idx}"

    # "every weekday at <H>(am|pm)" — Mon-Fri (1-5).
    if re.search(r"(?i)\bevery\s+weekday\b", text):
        m = _DAILY_AT_RE.search(text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            ampm = (m.group(3) or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return f"{minute} {hour} * * 1-5"

    # "every day at <H>(am|pm)" / "daily 6am" / "nightly at 11pm".
    m = _DAILY_AT_RE.search(text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm = (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return f"{minute} {hour} * * *"

    return None


def _is_slug_shaped(s: str) -> bool:
    """True iff `s` looks like a slug (lowercase letters/digits/hyphens/underscores,
    no spaces, length 2-40). Used to disambiguate the first positional in
    `hermes cron add 'NAME' 'SCHEDULE' 'PROMPT'` when --name flag is absent."""
    if not s or " " in s or len(s) < 2 or len(s) > 40:
        return False
    # Cron expressions contain digits, spaces, *, /, -, , — they're not slug-shaped
    # because they have spaces (caught above). But guard against pure-numeric input.
    return bool(re.match(r"^[a-z0-9][a-z0-9_-]+$", s))


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
        if a required field (schedule + prompt) cannot be determined.
        """
        steps = entry.implementation_steps or []
        haystack_parts = [
            *steps,
            entry.extracted_content or "",
            entry.notes or "",
            entry.title or "",
            entry.rationale or "",
        ]
        haystack = "\n".join(p for p in haystack_parts if p)

        # 1. Try to find a `hermes cron add ...` invocation we can parse.
        # Two shapes the LLM emits:
        #   (a) flag form: hermes cron add --name X --schedule Y --prompt Z   (legacy/wrong)
        #   (b) positional: hermes cron add [--name X] 'schedule' 'prompt'    (real CLI shape)
        # Try BOTH per step — first hit wins, with positional preferred since
        # that's what real hermes invocations look like.
        for step in steps:
            if "hermes cron add" not in step:
                continue
            name = _extract_quoted_after(step, "--name")
            profile_flag = _extract_quoted_after(step, "--profile")
            # Flag form (legacy)
            schedule = _extract_quoted_after(step, "--schedule")
            prompt = _extract_quoted_after(step, "--prompt")
            # Positional form: capture quoted strings AFTER the 'hermes cron add'
            # token, EXCLUDING any --flag=val or --flag val pairs.
            if not schedule or not prompt:
                # Strip the command prefix + any --flag value tokens, then grab
                # remaining quoted positional args.
                tail = step[step.index("hermes cron add") + len("hermes cron add") :]
                # Remove flag-and-value pairs (--name X, --profile Y, --deliver Z, etc.)
                stripped = re.sub(
                    r"\s+--(?:name|profile|deliver|repeat|skill|script|workdir)(?:[=\s]+['\"][^'\"]*['\"]|[=\s]+\S+)?",
                    " ",
                    tail,
                )
                # Also remove --no-agent (boolean flag with no value)
                stripped = re.sub(r"\s+--no-agent\b", " ", stripped)
                # Find quoted strings in order
                positionals = re.findall(r"['\"]([^'\"]+)['\"]", stripped)
                # If no quoted strings, try bare-token form (e.g., "every 2h" without quotes)
                if not positionals:
                    bare = stripped.strip().split(None, 1)
                    positionals = [t.strip() for t in bare if t.strip()]
                if len(positionals) >= 2:
                    if not schedule:
                        schedule = positionals[0]
                    if not prompt:
                        prompt = positionals[1] if len(positionals) > 1 else ""

            # Backfill missing name from positionals if name is the first positional
            # and looks slug-shaped (e.g., 'weekly-audit')
            if not name and schedule and _is_slug_shaped(schedule):
                # Re-shift: positionals[0]=name, [1]=schedule, [2]=prompt
                tail = step[step.index("hermes cron add") + len("hermes cron add") :]
                stripped = re.sub(
                    r"\s+--(?:name|profile|deliver|repeat|skill|script|workdir)(?:[=\s]+['\"][^'\"]*['\"]|[=\s]+\S+)?",
                    " ",
                    tail,
                )
                positionals = re.findall(r"['\"]([^'\"]+)['\"]", stripped)
                if len(positionals) >= 3:
                    name = positionals[0]
                    schedule = positionals[1]
                    prompt = positionals[2]

            profile = profile_flag or self._infer_profile(haystack)
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

        prompt = self._find_prompt(steps, entry.extracted_content or "", entry.rationale or "")
        if not prompt:
            return None

        # Name can come from an explicit --name or name: marker anywhere; else
        # we slugify the entry title or the prompt.
        name = self._find_explicit_name(haystack) or self._derive_name(entry, prompt)
        if not name:
            return None

        profile = self._infer_profile(haystack)
        return {
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "profile": profile if profile in _VALID_PROFILES else "default",
        }

    @staticmethod
    def _find_explicit_name(haystack: str) -> Optional[str]:
        """Look for an explicit ``--name <x>`` flag or ``name: <x>`` label."""
        m = re.search(r"--name[=\s]+['\"]?([A-Za-z0-9_\-]+)['\"]?", haystack)
        if m:
            return m.group(1)
        m = re.search(r"(?i)\bname\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{2,60})['\"]?", haystack)
        if m:
            return m.group(1)
        return None

    def _find_schedule(self, text: str) -> Optional[str]:
        """Find a cron-shaped or natural-language schedule string.

        Resolution order:
            1. Cron-shaped line (with optional `Schedule:` / `Cron:` / `When:` label)
            2. Cron-shaped substring anywhere in the text
            3. "every N minutes/hours/days/weeks" → standard cron form
            4. "every weekday at 8am" / "daily 6am" / "weekly on Monday at 10am" →
               natural-language phrase preserved (Hermes' English cron parser
               handles them natively)
            5. Generic natural-language fallback (e.g., "hourly", "nightly")
        """
        # 1. Labeled or bare cron-shaped lines.
        for line in text.splitlines():
            stripped = line.strip()
            # Skip command-shaped lines that contain the cron tool itself.
            if stripped.startswith("#") or not stripped:
                continue
            # Strip a `Schedule:` / `Cron:` / `When:` label prefix if present.
            label = re.match(r"(?i)(?:schedule|cron|when)\s*[:=]\s*", stripped)
            candidate_line = stripped[label.end() :] if label else stripped
            # Strip surrounding quotes/backticks from a quoted cron line.
            candidate_line = candidate_line.strip("`\"' ")
            tokens = candidate_line.split()
            if len(tokens) == 5 and all(self._is_cron_token(t) for t in tokens):
                return candidate_line
        m = _CRON_RE.search(text)
        if m:
            candidate = m.group(1).strip()
            if all(self._is_cron_token(t) for t in candidate.split()):
                return candidate
        # 2. "every N minute/hour/..." → cron expression.
        every_m = _EVERY_N_RE.search(text)
        if every_m:
            phrase = every_m.group(0)
            converted = _phrase_to_cron(phrase)
            if converted:
                return converted
        # 3. Natural-language phrase — preserved verbatim for Hermes' English parser.
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

    def _find_prompt(
        self,
        steps: list[str],
        extracted: str,
        rationale: str = "",
    ) -> Optional[str]:
        """Find the natural-language instruction Hermes should run.

        Resolution order:
            1. ``Prompt:`` / ``Instruction:`` / ``Cron task:`` labeled line
            2. Multi-line single- or triple-quoted block
            3. Any quoted 20-400 char string in the body
            4. ``entry.rationale`` as a last resort
        """
        # Look for an explicit labeled line.
        prompt_label_re = re.compile(
            r"\s*(?:prompt|instruction|cron\s+task|task)\s*[:=]\s*(.+)$",
            re.IGNORECASE,
        )
        for source in [*steps, extracted]:
            for line in source.splitlines():
                m = prompt_label_re.match(line)
                if m:
                    return m.group(1).strip().strip("`\"' ")
        # Look for a triple-quoted block.
        for source in [extracted, *steps]:
            m = re.search(r"\"{3}([\s\S]+?)\"{3}|'{3}([\s\S]+?)'{3}", source)
            if m:
                block = (m.group(1) or m.group(2) or "").strip()
                if len(block) >= 10:
                    return block
        # Look for a single-line single- or double-quoted string in the body.
        # Use a two-pass strategy: first try non-overlapping findall (skips
        # candidates ending in `:` which are label artifacts), then fall back
        # to overlapping search via re.finditer with lookahead so we can find
        # quoted bodies whose opening quote follows a possessive ('Hermes' ...).
        for source in [extracted, *steps]:
            non_overlapping = re.findall(r"['\"]([^'\"\n]{20,400})['\"]", source)
            viable = [c for c in non_overlapping if not c.rstrip().endswith(":")]
            if viable:
                return max(viable, key=len).strip()
            # Overlap-tolerant pass: same body shape, but allow restarting at
            # every quote so a missed match after a possessive is found.
            overlap = [m.group(1) for m in re.finditer(r"(?=['\"]([^'\"\n]{20,400})['\"])", source)]
            overlap_viable = [c for c in overlap if not c.rstrip().endswith(":")]
            if overlap_viable:
                return max(overlap_viable, key=len).strip()
            if non_overlapping:
                return max(non_overlapping, key=len).strip()
        # Final fallback: the entry's rationale (often a usable single-sentence prompt).
        if rationale:
            text = rationale.strip()
            if 10 <= len(text) <= 400:
                return text
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
        # hermes cron add uses POSITIONAL `<schedule> [prompt]`, not --schedule/--prompt flags.
        # Optional flags: --name, --profile, --deliver, --repeat, --skill, --script.
        return (
            f"# Would register Hermes cron (profile={spec.get('profile', 'default')}):\n"
            f"hermes cron add --name '{spec['name']}' '{spec['schedule']}' '{spec['prompt']}'\n"
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

        # `hermes cron add` is an alias for `cron create` with signature:
        #   hermes cron add [--name N] <schedule> [prompt]
        # Use HERMES_PROFILE env-var prefix for non-default profiles (consistent
        # with _list_existing_crons and rollback, which also use the prefix form).
        profile_prefix = (
            f"HERMES_PROFILE={shlex.quote(profile)} " if profile and profile != "default" else ""
        )
        cmd_str = (
            f"{profile_prefix}hermes cron add --name {shlex.quote(spec['name'])} "
            + f"{shlex.quote(spec['schedule'])} {shlex.quote(spec['prompt'])}"
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
