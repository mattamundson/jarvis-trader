"""Edits a single key in ~/.hermes/config.yaml.

Single-key edits are safer than mcp_adder's block-add because they touch a
single value (e.g. ``model.provider``, ``fallback_model.base_url``). YAML is
loaded via ruamel.yaml when available (preserves comments + ordering) and
falls back to PyYAML.

Backup contract:
    Every mutating apply() creates ``<cfg>.bak.<UTC-ts>`` first and records
    the restore command in ApplyResult.rollback_path.

Idempotency:
    If the current value at ``key_path`` already equals ``new_value``, apply()
    returns success with ``notes='idempotent skip'`` without writing.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shlex
from datetime import datetime, timezone
from typing import Any

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

HERMES_CONFIG_WSL_DEFAULT = "/home/mattm/.hermes/config.yaml"

WSL_TIMEOUT_S = 60

# Match `key.path: value` form (allow leading bullets/numbers, surrounding quotes).
# Examples it must match:
#   model.provider: anthropic
#   - fallback_model.base_url: "https://api.anthropic.com"
#   * features.enable_redact_secrets: true
KEY_VALUE_RE = re.compile(
    r"(?im)^\s*[-*\d.)\s]*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"\s*:\s*(?P<value>.+?)\s*$",
)

# Match `set X.Y(.Z…) to <value>` shape. Trailing sentence punctuation is
# stripped post-match in _extract_config_change (see below).
SET_RE = re.compile(
    r"(?i)\bset\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"\s+to\s+(?P<value>.+?)\s*$",
)


def _coerce_value(raw: str) -> Any:
    """Best-effort scalar coercion. Falls back to the stripped string."""
    stripped = raw.strip().strip("`")
    if not stripped:
        return stripped
    # Quoted string — keep as string, drop quotes.
    if (stripped.startswith('"') and stripped.endswith('"')) or (
        stripped.startswith("'") and stripped.endswith("'")
    ):
        return stripped[1:-1]
    low = stripped.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    # Try literal_eval (covers ints, floats, lists, dicts, bool).
    try:
        return ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        pass
    # Try JSON.
    try:
        return json.loads(stripped)
    except (ValueError, json.JSONDecodeError):
        return stripped


class ConfigPatcher(BaseApplier):
    """Applier for UpgradeType="config_improvement" backlog entries."""

    upgrade_type: UpgradeType = "config_improvement"

    def __init__(self, hermes_config_wsl: str | None = None) -> None:
        self.hermes_config_wsl = hermes_config_wsl or HERMES_CONFIG_WSL_DEFAULT

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _extract_config_change(self, entry: BacklogEntry) -> dict[str, Any] | None:
        """Return ``{key_path, new_value, reason}`` or None.

        Search order:
          1. ``set X.Y to Z`` shape (more explicit).
          2. ``X.Y: Z`` shape in implementation_steps.
        """
        steps = entry.implementation_steps or []
        reason = entry.rationale or entry.notes or "<from entry>"

        for step in steps:
            m = SET_RE.search(step)
            if m:
                raw_value = m.group("value").strip().rstrip(".,;:")
                return {
                    "key_path": m.group("key").strip(),
                    "new_value": _coerce_value(raw_value),
                    "reason": reason,
                }

        for step in steps:
            m = KEY_VALUE_RE.search(step)
            if m:
                return {
                    "key_path": m.group("key").strip(),
                    "new_value": _coerce_value(m.group("value")),
                    "reason": reason,
                }

        return None

    # ------------------------------------------------------------------
    # BaseApplier interface
    # ------------------------------------------------------------------
    async def dry_run(self, entry: BacklogEntry) -> str:
        chg = self._extract_config_change(entry)
        if not chg:
            return f"ERROR: could not extract config change from {entry.bookmark_id}"
        return (
            f"# Would patch {self.hermes_config_wsl}\n"
            f"# Path: {chg['key_path']}\n"
            f"# New value: {chg['new_value']!r}\n"
            f"# Backup: {self.hermes_config_wsl}.bak.<UTC-ts>\n"
            f"# Reason: {chg.get('reason', '<from entry>')}\n"
        )

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        chg = self._extract_config_change(entry)
        if not chg:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error="could not parse config change",
            )

        key_path = chg["key_path"]
        new_value = chg["new_value"]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{self.hermes_config_wsl}.bak.{ts}"

        script = self._build_patch_script(
            cfg_path=self.hermes_config_wsl,
            backup_path=backup_path,
            key_path=key_path,
            new_value=new_value,
        )

        # Pass the script via stdin to python3 to keep quoting bullet-proof.
        cmd = self._wsl_cmd("python3")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=script.encode("utf-8")),
                timeout=WSL_TIMEOUT_S,
            )
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            rc = proc.returncode
        except asyncio.TimeoutError:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=f"key={key_path} value={new_value!r}",
                post_apply_verification="",
                rollback_path=backup_path,
                error=f"config patch timed out after {WSL_TIMEOUT_S}s",
            )
        except OSError as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=f"key={key_path} value={new_value!r}",
                post_apply_verification="",
                rollback_path="",
                error=f"failed to launch wsl.exe: {exc}",
            )

        # Distinct exit code 3 = idempotent skip (value already equals new_value).
        if rc == 3:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {key_path} already equals {new_value!r}",
                post_apply_verification=(
                    f"grep -n {shlex.quote(key_path.split('.')[-1])} {self.hermes_config_wsl}"
                ),
                rollback_path="",
                notes="idempotent skip",
            )

        success = rc == 0 and "OK " in output
        if not success:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff=f"key={key_path} value={new_value!r}",
                post_apply_verification="",
                rollback_path=backup_path,
                error=f"yaml-mutate failed (rc={rc}): {output[-500:]}",
            )

        leaf = key_path.split(".")[-1]
        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff=f"key={key_path} value={new_value!r}",
            post_apply_verification=f"grep -n {shlex.quote(leaf)} {self.hermes_config_wsl}",
            rollback_path=f"cp {backup_path} {self.hermes_config_wsl}",
            notes=output[-500:],
        )

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        chg = self._extract_config_change(entry)
        if not chg:
            return False
        key_path = chg["key_path"]
        expected = chg["new_value"]
        return await self._read_value_equals(key_path, expected)

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
            await asyncio.wait_for(proc.communicate(), timeout=WSL_TIMEOUT_S)
            return proc.returncode == 0
        except (asyncio.TimeoutError, OSError):
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wsl_cmd(bash_cmd: str) -> list[str]:
        return ["wsl.exe", "-d", "Ubuntu", "-u", "mattm", "-e", "bash", "-lc", bash_cmd]

    @staticmethod
    def _build_patch_script(
        *,
        cfg_path: str,
        backup_path: str,
        key_path: str,
        new_value: Any,
    ) -> str:
        """Render the python3 stdin program that does the round-trip patch.

        Exit codes:
            0  -- patched successfully (stdout starts with ``OK ``)
            3  -- idempotent skip (current == new)
            non-zero otherwise -- failure, original file untouched if backup
                                  step ran first.
        """
        # Serialize new_value once via JSON so the script can decode it verbatim.
        new_value_json = json.dumps(new_value)
        return (
            "import json, sys, shutil\n"
            "try:\n"
            "    from ruamel.yaml import YAML\n"
            "    yaml = YAML()\n"
            "    yaml.preserve_quotes = True\n"
            "    backend = 'ruamel'\n"
            "except ImportError:\n"
            "    import yaml as _yaml\n"
            "    backend = 'pyyaml'\n"
            "\n"
            f"p = {cfg_path!r}\n"
            f"backup = {backup_path!r}\n"
            f"key_path = {key_path!r}\n"
            f"new_value = json.loads({new_value_json!r})\n"
            "\n"
            "shutil.copy(p, backup)\n"
            "\n"
            "if backend == 'ruamel':\n"
            "    with open(p) as f:\n"
            "        data = yaml.load(f) or {}\n"
            "else:\n"
            "    with open(p) as f:\n"
            "        data = _yaml.safe_load(f) or {}\n"
            "\n"
            "parts = key_path.split('.')\n"
            "parent = data\n"
            "for part in parts[:-1]:\n"
            "    if part not in parent or parent[part] is None:\n"
            "        parent[part] = {}\n"
            "    parent = parent[part]\n"
            "\n"
            "old = parent.get(parts[-1])\n"
            "if old == new_value:\n"
            "    sys.exit(3)\n"
            "\n"
            "parent[parts[-1]] = new_value\n"
            "\n"
            "if backend == 'ruamel':\n"
            "    with open(p, 'w') as f:\n"
            "        yaml.dump(data, f)\n"
            "else:\n"
            "    with open(p, 'w') as f:\n"
            "        _yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)\n"
            "\n"
            "print(f'OK old={old!r} new={new_value!r} backup={backup} backend={backend}')\n"
        )

    async def _read_value_equals(self, key_path: str, expected: Any) -> bool:
        """Return True iff the YAML at ``key_path`` equals ``expected``."""
        expected_json = json.dumps(expected)
        script = (
            "import json, sys\n"
            "try:\n"
            "    from ruamel.yaml import YAML\n"
            "    yaml = YAML()\n"
            "    use_ruamel = True\n"
            "except ImportError:\n"
            "    import yaml as _yaml\n"
            "    use_ruamel = False\n"
            f"p = {self.hermes_config_wsl!r}\n"
            f"key_path = {key_path!r}\n"
            f"expected = json.loads({expected_json!r})\n"
            "with open(p) as f:\n"
            "    data = yaml.load(f) if use_ruamel else _yaml.safe_load(f)\n"
            "data = data or {}\n"
            "node = data\n"
            "for part in key_path.split('.'):\n"
            "    if not isinstance(node, dict) or part not in node:\n"
            "        print('MISSING'); sys.exit(0)\n"
            "    node = node[part]\n"
            "print('MATCH' if node == expected else 'DIFFER')\n"
        )
        cmd = self._wsl_cmd("python3")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=script.encode("utf-8")),
                timeout=WSL_TIMEOUT_S,
            )
            return b"MATCH" in (stdout or b"")
        except (asyncio.TimeoutError, OSError):
            return False
