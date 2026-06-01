"""Pip-installs Python libraries into Hermes or GEPA venvs.

The applier is idempotent: a second apply() detects the package is already
installed (via `pip show`) and short-circuits with success.

Routing:
    Target venv is inferred from the entry's notes + implementation_steps +
    extracted_content. If any of those mention "gepa" or "self-evolution",
    the GEPA venv is targeted; otherwise the Hermes venv.

Invocation contract:
    All pip commands run inside the Ubuntu WSL distro as user `mattm`,
    invoked via `wsl.exe -d Ubuntu -u mattm -e bash -lc '<cmd>'`. A 300-second
    timeout is enforced on install; 30 seconds on the `pip show` query.

Rollback:
    rollback() runs `pip uninstall -y <pkg>` inside WSL. Errors are tolerated
    because the package may already have been removed.
"""

from __future__ import annotations

import asyncio
import re
import shlex

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

# Target venv pip binaries (WSL-side).
HERMES_VENV_PIP = "/home/mattm/.hermes/hermes-agent/venv/bin/pip"
GEPA_VENV_PIP = "/home/mattm/Code/hermes-agent-self-evolution/.venv/bin/pip"

INSTALL_TIMEOUT_S = 300
LIST_TIMEOUT_S = 30

# `pip install <spec>` — capture the package spec (allows extras + version pin).
PIP_INSTALL_RE = re.compile(
    r"pip\s+install\s+(?:--?[a-zA-Z0-9_-]+\s+)*([A-Za-z0-9_.\-\[\]=<>!~,*]+)",
)

# `uv add <spec>` / `uv pip install <spec>` — uv is a faster pip alternative.
UV_INSTALL_RE = re.compile(
    r"uv\s+(?:pip\s+install|add)\s+(?:--?[a-zA-Z0-9_-]+\s+)*([A-Za-z0-9_.\-\[\]=<>!~,*/]+)",
)

# `pip install -r <path>` — requirements file dispatch.
PIP_REQUIREMENTS_RE = re.compile(
    r"pip\s+install\s+-r\s+(\S+)",
)

# `pip install -e <path|url>` — editable install (clone + install pattern).
PIP_EDITABLE_RE = re.compile(
    r"pip\s+install\s+-e\s+(\S+)",
)

# GitHub clone + install pattern — captures "clone https://github.com/<org>/<repo>" near a
# pip-related verb. We synthesize a VCS-style spec for it.
GITHUB_CLONE_RE = re.compile(
    r"(?i)(?:git\s+clone|clone)\s+(https?://github\.com/[\w.-]+/[\w.-]+?)(?:\.git)?(?:\s|$)",
)

# "Install <pkg>" prose pattern — matches "Install foo", "install via X foo", with python
# library / package context.
INSTALL_PROSE_RE = re.compile(
    r"(?i)\binstall(?:\s+(?:via|using|with)\s+\S+)?\s+([A-Za-z][A-Za-z0-9_.\-]+)",
)

# Title-derived "<libname>: <description>" pattern.
TITLE_LIBNAME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_.\-]+)\s*[:\-]")

# Package-name root used for `pip show` and `pip uninstall` (strips extras + version).
_PKG_ROOT_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")

_PYTHON_LIBRARY_HINTS = ("python library", "python package", "pip install", "pypi", "py-package")


def _pkg_root(spec: str) -> str:
    """Strip ``[extras]`` and ``==version`` markers, leaving the bare distribution name.

    Special-cases:
        ``-r <path>`` / ``-e <path-or-url>`` return the bare spec (no `pip show`
        equivalent for these — the applier records the spec verbatim and skips
        the idempotency probe).
        VCS specs (``git+https://...``) return the inferred repo basename.
    """
    if spec.startswith("-r ") or spec.startswith("-e "):
        return spec
    if spec.startswith("git+"):
        # Try to derive the bare repo name as the importable package guess.
        m = re.search(r"/([^/]+?)(?:\.git)?$", spec)
        return m.group(1) if m else spec
    m = _PKG_ROOT_RE.match(spec)
    return m.group(1) if m else spec


class LibraryIntegrator(BaseApplier):
    """Applier for UpgradeType="library" backlog entries."""

    upgrade_type: UpgradeType = "library"

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _extract_pip_spec(self, entry: BacklogEntry) -> tuple[str, str] | None:
        """Return ``(target_venv, package_spec)`` or None.

        ``target_venv`` is ``"hermes"`` or ``"gepa"``. The package_spec is the
        raw token following ``pip install`` (preserving extras + version pin).
        Routing is determined by inspecting notes / implementation_steps /
        extracted_content / title for "gepa" or "self-evolution".

        Recognized patterns (tried in order, all-fields scan):
            1. ``pip install <pkg>``
            2. ``uv add <pkg>`` / ``uv pip install <pkg>``
            3. ``pip install -r requirements.txt``
            4. ``pip install -e <path-or-url>`` / git clone + install (synthesized)
            5. ``Install <pkg>`` prose with python-library/package hint
            6. ``<libname>: <description>`` title shape with python-library hint
        """
        steps = entry.implementation_steps or []
        title = entry.title or ""
        notes = entry.notes or ""
        extracted = entry.extracted_content or ""
        # Search across ALL fields for the install verb (was steps-only previously).
        sources: list[str] = [*steps, extracted, notes, title]

        # Check -r/-e specials FIRST so they aren't swallowed by PIP_INSTALL_RE's
        # generic flag-consumer.
        package = None
        req = self._first_match(sources, PIP_REQUIREMENTS_RE)
        if req:
            package = f"-r {req}"
        if package is None:
            editable = self._first_match(sources, PIP_EDITABLE_RE)
            if editable:
                package = f"-e {editable}"
        if package is None:
            # git clone + pip install . (no -e flag) — synthesize a VCS spec.
            # Checked BEFORE PIP_INSTALL_RE so we don't capture the trailing "."
            # as the package name.
            for src in sources:
                m = GITHUB_CLONE_RE.search(src)
                if m and re.search(r"(?i)pip\s+install|setup\.py|pyproject\.toml", src):
                    package = f"git+{m.group(1)}"
                    break
        if package is None:
            package = self._first_match(sources, PIP_INSTALL_RE)
        if package is None:
            package = self._first_match(sources, UV_INSTALL_RE)
        if package is None:
            # Title-derived "<libname>: <description>" with python-library hint anywhere.
            haystack_lower = "\n".join(sources).lower()
            if any(hint in haystack_lower for hint in _PYTHON_LIBRARY_HINTS):
                m = TITLE_LIBNAME_RE.match(title)
                if m:
                    package = m.group(1)
        if package is None:
            # Prose "install <pkg>" + python-library hint in any field.
            haystack_lower = "\n".join(sources).lower()
            if any(hint in haystack_lower for hint in _PYTHON_LIBRARY_HINTS):
                for src in sources:
                    m = INSTALL_PROSE_RE.search(src)
                    if m:
                        candidate = m.group(1).strip("`\"' ")
                        # Skip noise verbs that match the prose regex.
                        if candidate.lower() not in {
                            "via",
                            "using",
                            "with",
                            "the",
                            "python",
                            "pip",
                            "uv",
                        }:
                            package = candidate
                            break

        if not package:
            return None
        package = package.strip("`\"' ")

        # Route to gepa venv if any field references the GEPA / self-evolution context.
        haystack = "\n".join(sources).lower()
        target_venv = "gepa" if ("gepa" in haystack or "self-evolution" in haystack) else "hermes"
        return target_venv, package

    @staticmethod
    def _first_match(sources: list[str], pattern: re.Pattern[str]) -> str | None:
        """Return first capture group across `sources` for `pattern`, or None."""
        for src in sources:
            if not src:
                continue
            m = pattern.search(src)
            if m:
                return m.group(1).strip("`\"' ")
        return None

    # ------------------------------------------------------------------
    # BaseApplier interface
    # ------------------------------------------------------------------
    async def dry_run(self, entry: BacklogEntry) -> str:
        spec = self._extract_pip_spec(entry)
        if not spec:
            return f"ERROR: could not extract pip install from {entry.bookmark_id}"
        target_venv, package = spec
        pip_bin = HERMES_VENV_PIP if target_venv == "hermes" else GEPA_VENV_PIP
        pkg_root = _pkg_root(package)
        return (
            f"# Would install (target_venv={target_venv}):\n"
            f"{pip_bin} install {package}\n"
            f"# Verify:\n"
            f"{pip_bin} show {pkg_root}\n"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        spec = self._extract_pip_spec(entry)
        if not spec:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error="could not parse pip install spec",
            )

        target_venv, package = spec
        pip_bin = HERMES_VENV_PIP if target_venv == "hermes" else GEPA_VENV_PIP
        pkg_root = _pkg_root(package)

        # Idempotency: short-circuit if `pip show` finds the package.
        if await self._is_installed(pip_bin, package):
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {package} already installed in {target_venv} venv",
                post_apply_verification=f"{pip_bin} show {pkg_root}",
                rollback_path=f"{pip_bin} uninstall -y {pkg_root}",
                notes="idempotent skip",
            )

        # `-r <path>` / `-e <path>` are flag+arg pairs and must NOT be quoted as
        # a single token. Split and quote the path piece independently.
        if package.startswith("-r ") or package.startswith("-e "):
            flag, _, target = package.partition(" ")
            cmd_str = f"{pip_bin} install {flag} {shlex.quote(target)}"
        else:
            cmd_str = f"{pip_bin} install {shlex.quote(package)}"
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._wsl_cmd(cmd_str),
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
                pre_apply_diff=cmd_str,
                post_apply_verification="",
                rollback_path="",
                error=f"pip install timed out after {INSTALL_TIMEOUT_S}s",
            )
        except OSError as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=cmd_str,
                post_apply_verification="",
                rollback_path="",
                error=f"failed to launch wsl.exe: {exc}",
            )

        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=success,
            pre_apply_diff=cmd_str,
            post_apply_verification=f"{pip_bin} show {pkg_root}",
            rollback_path=f"{pip_bin} uninstall -y {pkg_root}",
            notes=f"output: {output[-500:]}",
            error=None if success else f"non-zero exit ({proc.returncode}); see notes",
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        spec = self._extract_pip_spec(entry)
        if not spec:
            return False
        target_venv, package = spec
        pip_bin = HERMES_VENV_PIP if target_venv == "hermes" else GEPA_VENV_PIP
        return await self._is_installed(pip_bin, package)

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        if not result.rollback_path:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._wsl_cmd(f"{result.rollback_path} 2>&1 || true"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(proc.communicate(), timeout=INSTALL_TIMEOUT_S)
            return proc.returncode == 0
        except (asyncio.TimeoutError, OSError):
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wsl_cmd(bash_cmd: str) -> list[str]:
        """Build the canonical wsl.exe invocation for a bash one-liner."""
        return ["wsl.exe", "-d", "Ubuntu", "-u", "mattm", "-e", "bash", "-lc", bash_cmd]

    async def _is_installed(self, pip_bin: str, package: str) -> bool:
        """Return True iff `pip show <pkg_root>` reports the package.

        For ``-r`` / ``-e`` / ``git+`` specs, idempotency cannot be probed via
        ``pip show`` (no single distribution name to look up), so we return
        False unconditionally — the install will run, but pip itself is
        idempotent for already-satisfied requirements.
        """
        if package.startswith("-r ") or package.startswith("-e ") or package.startswith("git+"):
            return False
        pkg_root = _pkg_root(package)
        cmd = self._wsl_cmd(f"{pip_bin} show {shlex.quote(pkg_root)} 2>/dev/null")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=LIST_TIMEOUT_S)
            return bool(stdout) and b"Name:" in stdout
        except (asyncio.TimeoutError, OSError):
            return False
