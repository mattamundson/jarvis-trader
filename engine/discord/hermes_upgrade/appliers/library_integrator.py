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

# Package-name root used for `pip show` and `pip uninstall` (strips extras + version).
_PKG_ROOT_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")


def _pkg_root(spec: str) -> str:
    """Strip ``[extras]`` and ``==version`` markers, leaving the bare distribution name."""
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
        extracted_content for "gepa" or "self-evolution".
        """
        steps = entry.implementation_steps or []
        package: str | None = None
        for step in steps:
            m = PIP_INSTALL_RE.search(step)
            if m:
                package = m.group(1).strip("`\"' ")
                break

        if not package:
            return None

        haystack = "\n".join(
            [
                entry.notes or "",
                entry.extracted_content or "",
                *steps,
            ]
        ).lower()
        target_venv = "gepa" if ("gepa" in haystack or "self-evolution" in haystack) else "hermes"
        return target_venv, package

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
        """Return True iff `pip show <pkg_root>` reports the package."""
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
