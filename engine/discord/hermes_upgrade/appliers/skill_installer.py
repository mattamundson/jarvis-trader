"""Installs Hermes skills via `hermes skills install <slug-or-url>` (WSL-side).

The applier is idempotent: a second apply() detects the skill is already
present (via `hermes skills list`) and short-circuits with success.

Invocation contract:
    All Hermes commands run inside the Ubuntu WSL distro as user `mattm`,
    invoked via `wsl.exe -d Ubuntu -u mattm -e bash -lc '<cmd>'`. A 120-second
    timeout is enforced on install; 30 seconds on the listing query.

Rollback:
    rollback() runs `hermes skills uninstall <target>` inside WSL. Errors are
    swallowed (|| true) because the skill may already have been removed by
    another path.
"""

from __future__ import annotations

import asyncio
import re

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

SKILL_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_./-]+$")
# Plain URL match — used as a fallback when no `hermes skills install` token is found.
GIT_URL_RE = re.compile(r"https?://(?:github\.com|gitlab\.com)/[^/\s]+/[^/\s)\"'`]+")
# "Clone <url> ..." — first capture group is the URL.
CLONE_URL_RE = re.compile(r"clone\s+(https?://(?:github|gitlab)\.com/[^\s)\"'`]+)", re.IGNORECASE)
# Owner/repo-style title (e.g. "ghumare64/AgentMemory" or "foo/bar").
TITLE_SLUG_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_./-]+$")

INSTALL_TIMEOUT_S = 120
LIST_TIMEOUT_S = 30


class SkillInstaller(BaseApplier):
    """Applier for UpgradeType="skill" backlog entries."""

    upgrade_type: UpgradeType = "skill"

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _extract_slug_or_url(self, entry: BacklogEntry) -> str | None:
        """Pull a slug or git URL out of an entry.

        Priority order (first hit wins):
          1. ``hermes skills install <X>`` token in any implementation_step
          2. github/gitlab URL inside any implementation_step
          3. github/gitlab URL inside extracted_content
          4. github/gitlab URL inside notes
          5. ``clone <url>`` regex hit across any of the above fields
          6. Title that looks like ``org/repo``
          7. None

        The returned value is normalized — trailing slashes removed, surrounding
        quote/backtick/paren noise stripped, and (for the install-command path)
        ``.git`` suffix + ``?ref=...`` query strings removed because Hermes'
        ``hermes skills install`` expects a slug-style identifier, not a raw URL.
        """
        # 1. Explicit `hermes skills install <X>` token wins.
        for step in entry.implementation_steps:
            m = re.search(r"hermes\s+skill\s+install\s+(\S+)", step)
            if m:
                return self._normalize_for_install(m.group(1))

        # 2. URL inside any implementation_step.
        for step in entry.implementation_steps:
            m = GIT_URL_RE.search(step)
            if m:
                return self._normalize_url(m.group(0))

        # 3. URL inside extracted_content.
        m = GIT_URL_RE.search(entry.extracted_content or "")
        if m:
            return self._normalize_url(m.group(0))

        # 4. URL inside notes.
        m = GIT_URL_RE.search(entry.notes or "")
        if m:
            return self._normalize_url(m.group(0))

        # 5. "Clone <url>" pattern across all the same fields.
        haystacks: list[str] = []
        haystacks.extend(entry.implementation_steps)
        if entry.extracted_content:
            haystacks.append(entry.extracted_content)
        if entry.notes:
            haystacks.append(entry.notes)
        for text in haystacks:
            m = CLONE_URL_RE.search(text)
            if m:
                return self._normalize_url(m.group(1))

        # 6. Title-derived slug — only if it cleanly matches org/repo shape.
        title = (entry.title or "").strip(" `\"'")
        if TITLE_SLUG_RE.match(title):
            return title

        return None

    @staticmethod
    def _normalize_url(target: str) -> str:
        """Strip surrounding noise (quotes/backticks/parens) and trailing punctuation."""
        return target.strip("`\"' ()<>,.;")

    @staticmethod
    def _normalize_for_install(target: str) -> str:
        """Normalize a hermes-skill-install argument.

        Hermes' ``hermes skills install`` expects a slug or a bare git URL; it
        does NOT need a trailing ``.git`` and chokes on query strings. Strip:

        * surrounding quotes / backticks / parens
        * trailing ``.git``
        * ``?ref=...`` (or any other query string)
        """
        stripped = SkillInstaller._normalize_url(target)
        # Drop query string.
        stripped = stripped.split("?", 1)[0]
        # Drop trailing .git only when invoking install (URL is what Hermes wants).
        if stripped.endswith(".git"):
            stripped = stripped[: -len(".git")]
        return stripped

    def _slug_root(self, target: str) -> str:
        """Derive the bare skill name from a slug or git URL.

        Examples:
            "owner/repo"            -> "repo"
            "https://github.com/owner/repo.git" -> "repo"
            "https://github.com/owner/repo"     -> "repo"
            "https://github.com/owner/repo?ref=main" -> "repo"
        """
        stripped = target.strip("`\"' ()<>,.;").rstrip("/")
        stripped = stripped.split("?", 1)[0]
        if stripped.endswith(".git"):
            stripped = stripped[: -len(".git")]
        return stripped.split("/")[-1]

    # ------------------------------------------------------------------
    # BaseApplier interface
    # ------------------------------------------------------------------
    async def dry_run(self, entry: BacklogEntry) -> str:
        target = self._extract_slug_or_url(entry)
        if not target:
            return f"ERROR: could not extract skill slug/url from entry {entry.bookmark_id}"
        slug_root = self._slug_root(target)
        return (
            "# Would run inside WSL Ubuntu (user mattm):\n"
            f"hermes skills install {target}\n"
            "# Then verify:\n"
            f"hermes skills list | grep -F {slug_root}"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        target = self._extract_slug_or_url(entry)
        if not target:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error=f"no skill slug/url found in entry {entry.bookmark_id}",
            )

        slug_root = self._slug_root(target)

        # Idempotency: skip if already installed.
        existing = await self._list_installed_skills()
        if any(slug_root in s for s in existing):
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {target} already installed",
                post_apply_verification=f"hermes skills list | grep -F {slug_root}",
                rollback_path=f"hermes skills uninstall {target}",
                notes="idempotent skip",
            )

        # Convert github repo URL → owner/repo slug form (hermes skills install
        # expects either a slug or a direct SKILL.md URL, not a repo root URL).
        install_target = target
        gh_match = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", target)
        if gh_match:
            install_target = gh_match.group(1)
        cmd = self._wsl_cmd(f"hermes skills install --yes '{install_target}' 2>&1")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=INSTALL_TIMEOUT_S)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            success = proc.returncode == 0
        except asyncio.TimeoutError:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=f"hermes skills install {target}",
                post_apply_verification="",
                rollback_path="",
                error=f"install timed out after {INSTALL_TIMEOUT_S}s",
            )

        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=success,
            pre_apply_diff=f"hermes skills install {target}",
            post_apply_verification=f"hermes skills list | grep -F {slug_root}",
            rollback_path=f"hermes skills uninstall {target}",
            notes=f"output: {output[-500:]}",
            error=None if success else f"non-zero exit ({proc.returncode}); see notes",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        target = self._extract_slug_or_url(entry)
        if not target:
            return False
        slug_root = self._slug_root(target)
        installed = await self._list_installed_skills()
        return any(slug_root in s for s in installed)

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        target = self._extract_slug_or_url(entry)
        if not target:
            return False
        cmd = self._wsl_cmd(f"hermes skills uninstall '{target}' 2>&1 || true")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(proc.communicate(), timeout=INSTALL_TIMEOUT_S)
            return proc.returncode == 0
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wsl_cmd(bash_cmd: str) -> list[str]:
        """Build the canonical wsl.exe invocation for a bash one-liner."""
        return ["wsl.exe", "-d", "Ubuntu", "-u", "mattm", "-e", "bash", "-lc", bash_cmd]

    async def _list_installed_skills(self) -> list[str]:
        """Return non-empty lines from `hermes skills list`; empty list on any error."""
        cmd = self._wsl_cmd("hermes skills list 2>&1 || echo __HERMES_LIST_ERROR__")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=LIST_TIMEOUT_S)
            text = stdout.decode("utf-8", errors="replace") if stdout else ""
            if proc.returncode != 0 or "__HERMES_LIST_ERROR__" in text:
                return []
            return [line.strip() for line in text.splitlines() if line.strip()]
        except (asyncio.TimeoutError, OSError):
            return []
