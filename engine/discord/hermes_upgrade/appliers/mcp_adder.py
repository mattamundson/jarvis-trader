"""Adds MCP server entries to ~/.hermes/config.yaml or ~/.claude.json.

Routing:
    If the backlog entry's implementation_steps or notes mention "claude.json"
    or "claude code", the entry is routed to ~/.claude.json (Windows-side).
    Otherwise it's routed to /home/mattm/.hermes/config.yaml (WSL-side, edited
    via wsl.exe + a python3 heredoc to keep YAML safety enforcement WSL-local).

Backup contract:
    Every mutating apply() call creates a sibling `.bak.<UTC-ts>` copy and
    records that path in ApplyResult.rollback_path. rollback() restores the
    most-recent backup associated with the result.

Spec format (parsed from implementation_steps):
    name: <server_name>
    command: <executable_path_or_name>
    args: ["arg1", "arg2"]  (optional)
    env: {"KEY": "VALUE"}   (optional)
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import ApplyResult, BacklogEntry, UpgradeType
from .base import BaseApplier

# Default canonical paths. Tests override via subclassing / monkeypatch.
CLAUDE_JSON_DEFAULT = Path(r"C:\Users\mattm\.claude.json")
HERMES_CONFIG_WSL_DEFAULT = "/home/mattm/.hermes/config.yaml"

WSL_TIMEOUT_S = 60


class McpAdder(BaseApplier):
    """Applier for UpgradeType="mcp_server" backlog entries."""

    upgrade_type: UpgradeType = "mcp_server"

    def __init__(
        self,
        claude_json_path: Path | None = None,
        hermes_config_wsl: str | None = None,
    ) -> None:
        self.claude_json_path = claude_json_path or CLAUDE_JSON_DEFAULT
        self.hermes_config_wsl = hermes_config_wsl or HERMES_CONFIG_WSL_DEFAULT

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_mcp_spec(self, entry: BacklogEntry) -> dict[str, Any] | None:
        """Extract ``{name, command, args?, env?, _target?, _human_required?}``.

        The LLM classifier rarely produces literal ``name:`` / ``command:``
        lines. This method tries a sequence of patterns from most-structured
        to least-structured, falling back to a "human required" candidate
        spec when only a URL + MCP-context is found.

        Search order:
            1. Strict ``name:`` / ``command:`` field block across all fields
            2. JSON-fenced block extraction (```json ...```)
            3. GitHub repo + MCP keyword -> synthesize npx spec
            4. ``npm install -g <pkg>`` or ``npx <pkg>`` -> synthesize npx spec
            5. ``python -m <module>`` -> synthesize python spec
            6. URL-only with MCP context -> flagged human_required candidate
            7. Return None

        The returned dict always carries a ``_target`` hint with one of:
            "claude_json", "hermes_yaml", "unknown".

        ``_human_required=True`` indicates the spec is a best-guess scaffold
        that an operator should review before applying.
        """
        haystack = self._build_haystack(entry)
        if not haystack:
            return None

        target = self._resolve_target(entry)

        # 1. Strict literal name:/command:/args: block.
        strict = self._parse_strict_block(haystack)
        if strict is not None:
            strict["_target"] = target
            return strict

        # 2. JSON fenced block.
        fenced = self._parse_json_fence(haystack)
        if fenced is not None:
            fenced["_target"] = target
            return fenced

        # 3. GitHub repo + MCP keyword.
        repo_spec = self._parse_github_mcp(haystack)
        if repo_spec is not None:
            repo_spec["_target"] = target
            return repo_spec

        # 4. npm install / npx form.
        npm_spec = self._parse_npm(haystack)
        if npm_spec is not None:
            npm_spec["_target"] = target
            return npm_spec

        # 5. python -m module form.
        py_spec = self._parse_python_module(haystack)
        if py_spec is not None:
            py_spec["_target"] = target
            return py_spec

        # 6. URL-only with MCP context.
        url_spec = self._parse_url_only(haystack, entry.title)
        if url_spec is not None:
            url_spec["_target"] = target
            return url_spec

        return None

    @staticmethod
    def _build_haystack(entry: BacklogEntry) -> str:
        """Concatenate implementation_steps + notes + extracted_content."""
        parts: list[str] = []
        parts.extend(entry.implementation_steps or [])
        if entry.notes:
            parts.append(entry.notes)
        if entry.extracted_content:
            parts.append(entry.extracted_content)
        if entry.title:
            parts.append(entry.title)
        return "\n".join(parts)

    @staticmethod
    def _has_mcp_keyword(text: str) -> bool:
        low = text.lower()
        return "mcp server" in low or "mcp:" in low or " mcp " in low or "mcp-server" in low

    def _parse_strict_block(self, text: str) -> dict[str, Any] | None:
        """Original strict parser — name:/command:/args:/env: lines."""
        name = self._extract_field(text, "name")
        command = self._extract_field(text, "command")
        if not name or not command:
            return None

        spec: dict[str, Any] = {"name": name, "command": command}

        args_raw = self._extract_field(text, "args")
        if args_raw:
            parsed = self._safe_literal(args_raw)
            if isinstance(parsed, list):
                spec["args"] = parsed

        env_raw = self._extract_field(text, "env")
        if env_raw:
            parsed = self._safe_literal(env_raw)
            if isinstance(parsed, dict):
                spec["env"] = parsed

        return spec

    @staticmethod
    def _parse_json_fence(text: str) -> dict[str, Any] | None:
        """Look for ```json ...``` blocks and parse the first MCP-shaped one."""
        for m in re.finditer(r"```(?:json)?\s*(.+?)```", text, re.DOTALL | re.IGNORECASE):
            blob = m.group(1).strip()
            try:
                data = json.loads(blob)
            except (ValueError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            # Standard MCP shape: {"name": ..., "command": ...}
            if "name" in data and "command" in data:
                spec: dict[str, Any] = {"name": data["name"], "command": data["command"]}
                if isinstance(data.get("args"), list):
                    spec["args"] = data["args"]
                if isinstance(data.get("env"), dict):
                    spec["env"] = data["env"]
                return spec
            # Alternative claude.json shape:
            # {"mcpServers": {"name": {"command": ..., "args": [...]}}}
            servers = data.get("mcpServers") or data.get("mcp_servers")
            if isinstance(servers, dict) and servers:
                name, block = next(iter(servers.items()))
                if isinstance(block, dict) and "command" in block:
                    spec = {"name": name, "command": block["command"]}
                    if isinstance(block.get("args"), list):
                        spec["args"] = block["args"]
                    if isinstance(block.get("env"), dict):
                        spec["env"] = block["env"]
                    return spec
        return None

    @staticmethod
    def _parse_github_mcp(text: str) -> dict[str, Any] | None:
        """github.com/<org>/<repo> + MCP keyword -> npx best-guess."""
        if not McpAdder._has_mcp_keyword(text):
            return None
        # Match github URLs; capture org+repo.
        m = re.search(
            r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:[/#?\s)\]]|\.git|$)",
            text,
        )
        if not m:
            return None
        org, repo = m.group(1), m.group(2).rstrip(".")
        # Strip trailing punctuation that crept in.
        repo = repo.rstrip(".,;:)")
        if not repo:
            return None
        repo_url = f"https://github.com/{org}/{repo}"
        return {
            "name": repo,
            "command": "npx",
            "args": ["-y", repo_url],
            "_human_required": True,
        }

    @staticmethod
    def _parse_npm(text: str) -> dict[str, Any] | None:
        """``npm install -g <pkg>`` or ``npx <pkg>`` -> npx spec."""
        # npm install -g foo  /  npm i -g foo  /  npm install foo
        m = re.search(
            r"npm\s+(?:install|i)\s+(?:-g\s+)?(?P<pkg>[@A-Za-z0-9_./-]+)",
            text,
            re.IGNORECASE,
        )
        if not m:
            # npx <pkg> [args...]
            m = re.search(
                r"\bnpx\s+(?:-y\s+)?(?P<pkg>[@A-Za-z0-9_./-]+)",
                text,
                re.IGNORECASE,
            )
        if not m:
            return None
        pkg = m.group("pkg").rstrip(".,;:)")
        if not pkg or pkg.lower() in ("install", "i", "-g"):
            return None
        # Derive a short name from the package: drop leading @scope/.
        short = pkg.split("/")[-1] if pkg.startswith("@") else pkg
        return {
            "name": short,
            "command": "npx",
            "args": ["-y", pkg],
            "_human_required": True,
        }

    @staticmethod
    def _parse_python_module(text: str) -> dict[str, Any] | None:
        """``python -m <module>`` -> python spec."""
        m = re.search(
            r"\bpython3?(?:\.exe)?\s+-m\s+(?P<mod>[A-Za-z_][A-Za-z0-9_.]+)",
            text,
        )
        if not m:
            return None
        module = m.group("mod").rstrip(".,;:)")
        return {
            "name": module.split(".")[-1],
            "command": "python",
            "args": ["-m", module],
            "_human_required": True,
        }

    @staticmethod
    def _parse_url_only(text: str, title: str) -> dict[str, Any] | None:
        """URL + MCP context fallback. Returns a human-required scaffold."""
        if not McpAdder._has_mcp_keyword(text):
            return None
        m = re.search(r"https?://[^\s)>\]]+", text)
        if not m:
            return None
        url = m.group(0).rstrip(".,;:)")
        slug = re.sub(r"[^a-z0-9]+", "-", (title or "mcp-server").lower()).strip("-")
        slug = slug or "mcp-server"
        # Cap slug length to keep config tidy.
        if len(slug) > 60:
            slug = slug[:60].rstrip("-")
        return {
            "name": slug,
            "command": "echo",
            "args": [url],
            "_human_required": True,
        }

    @staticmethod
    def _extract_field(text: str, key: str) -> str | None:
        """Pull ``key: <rest-of-line>`` from a multi-line spec block.

        Strips bullet/leader chars (``- `` / ``* `` / numbered list) and
        surrounding whitespace. Returns None if key not found.
        """
        pattern = rf"(?im)^\s*[-*\d.)\s]*{re.escape(key)}\s*:\s*(.+?)\s*$"
        m = re.search(pattern, text)
        if not m:
            return None
        return m.group(1).strip().strip("`\"'")

    @staticmethod
    def _safe_literal(raw: str) -> Any:
        """Try literal_eval, then JSON, return None on failure."""
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            pass
        try:
            return json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None

    def _target_is_claude_code(self, entry: BacklogEntry) -> bool:
        """True iff the entry references Claude Code / claude.json."""
        haystack = self._target_haystack(entry)
        return any(
            key in haystack
            for key in ("claude.json", "claude code", "~/.claude.json", "mcpservers")
        )

    def _target_is_hermes(self, entry: BacklogEntry) -> bool:
        """True iff the entry references Hermes config.yaml."""
        haystack = self._target_haystack(entry)
        return any(
            key in haystack
            for key in (
                "hermes config",
                ".hermes/config",
                "mcp_servers",
                "hermes-gateway",
                "/home/mattm/.hermes",
            )
        )

    @staticmethod
    def _target_haystack(entry: BacklogEntry) -> str:
        parts = list(entry.implementation_steps or [])
        parts.append(entry.notes or "")
        parts.append(entry.extracted_content or "")
        return "\n".join(parts).lower()

    def _resolve_target(self, entry: BacklogEntry) -> str:
        """Return 'claude_json', 'hermes_yaml', or 'unknown'."""
        is_claude = self._target_is_claude_code(entry)
        is_hermes = self._target_is_hermes(entry)
        if is_claude and not is_hermes:
            return "claude_json"
        if is_hermes and not is_claude:
            return "hermes_yaml"
        if is_claude and is_hermes:
            # Prefer claude.json if explicit "claude code" mention is present.
            return "claude_json"
        return "unknown"

    # ------------------------------------------------------------------
    # BaseApplier interface
    # ------------------------------------------------------------------
    async def dry_run(self, entry: BacklogEntry) -> str:
        spec = self._parse_mcp_spec(entry)
        if not spec:
            return f"ERROR: could not parse MCP spec from {entry.bookmark_id}"
        target_label = (
            "~/.claude.json" if self._target_is_claude_code(entry) else "~/.hermes/config.yaml"
        )
        human_required = spec.get("_human_required") is True
        server_block = self._public_block(spec)
        header = ""
        if human_required:
            header = (
                "# WARNING: spec was synthesized from a best-guess pattern. "
                "Review before applying.\n"
            )
        return (
            f"{header}"
            f"# Would add to {target_label} under "
            f"{'mcpServers' if target_label.endswith('.json') else 'mcp_servers'}:\n"
            f"{json.dumps({spec['name']: server_block}, indent=2)}\n"
            f"# Backup will be written to {target_label}.bak.<UTC-timestamp>"
        )

    @staticmethod
    def _public_block(spec: dict[str, Any]) -> dict[str, Any]:
        """Return spec sans ``name`` and any private ``_*`` keys."""
        return {k: v for k, v in spec.items() if k != "name" and not k.startswith("_")}

    async def apply(self, entry: BacklogEntry) -> ApplyResult:
        spec = self._parse_mcp_spec(entry)
        if not spec:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error="could not parse MCP spec",
            )

        if self._target_is_claude_code(entry):
            return await self._add_to_claude_json(entry, spec)
        return await self._add_to_hermes_yaml(entry, spec)

    async def verify(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        spec = self._parse_mcp_spec(entry)
        if not spec:
            return False
        target_name = spec["name"]

        if self._target_is_claude_code(entry):
            try:
                data = json.loads(self.claude_json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            return target_name in (data.get("mcpServers") or {})

        # WSL-side YAML verification
        script = (
            "import yaml,sys;"
            f"d=yaml.safe_load(open('{self.hermes_config_wsl}'))"
            " or {};"
            "k=list((d.get('mcp_servers') or {}).keys());"
            f"print('FOUND' if '{target_name}' in k else 'MISSING')"
        )
        cmd = self._wsl_cmd(f'python3 -c "{script}"')
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=WSL_TIMEOUT_S)
            return b"FOUND" in (stdout or b"")
        except (asyncio.TimeoutError, OSError):
            return False

    async def rollback(self, entry: BacklogEntry, result: ApplyResult) -> bool:
        backup = result.rollback_path
        if not backup:
            return False

        if self._target_is_claude_code(entry):
            backup_path = Path(backup)
            if not backup_path.exists():
                return False
            try:
                shutil.copy2(backup_path, self.claude_json_path)
                return True
            except OSError:
                return False

        # WSL-side restore: `cp <backup> <config>`
        cmd = self._wsl_cmd(f"cp '{backup}' '{self.hermes_config_wsl}'")
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
    # claude.json (Windows-side)
    # ------------------------------------------------------------------
    async def _add_to_claude_json(
        self,
        entry: BacklogEntry,
        spec: dict[str, Any],
    ) -> ApplyResult:
        path = self.claude_json_path
        if not path.exists():
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error=f"claude.json not found at {path}",
            )

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error=f"failed to read/parse claude.json: {exc}",
            )

        servers = data.setdefault("mcpServers", {})
        name = spec["name"]

        if name in servers:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {name} already present in mcpServers",
                post_apply_verification=f"jq '.mcpServers.\"{name}\"' {path}",
                rollback_path="",
                notes="idempotent skip",
            )

        # Create timestamped backup before mutating.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = path.with_suffix(path.suffix + f".bak.{ts}")
        try:
            shutil.copy2(path, backup_path)
        except OSError as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error=f"failed to create backup: {exc}",
            )

        server_block = self._public_block(spec)
        servers[name] = server_block

        try:
            self._atomic_write_json(path, data)
        except OSError as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path=str(backup_path),
                error=f"failed to write updated claude.json: {exc}",
            )

        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff=(
                f"# Added to {path} under mcpServers:\n"
                f"{json.dumps({name: server_block}, indent=2)}"
            ),
            post_apply_verification=f"jq '.mcpServers.\"{name}\"' {path}",
            rollback_path=str(backup_path),
            notes="claude.json updated",
        )

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        """Write JSON via tempfile + shutil.move to avoid partial writes."""
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            suffix=".tmp",
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp.flush()
            tmp_name = tmp.name
        shutil.move(tmp_name, path)

    # ------------------------------------------------------------------
    # ~/.hermes/config.yaml (WSL-side)
    # ------------------------------------------------------------------
    async def _add_to_hermes_yaml(
        self,
        entry: BacklogEntry,
        spec: dict[str, Any],
    ) -> ApplyResult:
        name = spec["name"]
        server_block = self._public_block(spec)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{self.hermes_config_wsl}.bak.{ts}"

        spec_json = json.dumps({name: server_block})
        # The heredoc runs python3 on the WSL side so PyYAML enforces YAML
        # safety natively. The script exits 2 on idempotent-skip so the
        # outer wrapper can distinguish added vs already-present.
        script = (
            "import json, sys, yaml, pathlib;"
            f"cfg=pathlib.Path('{self.hermes_config_wsl}');"
            "data=yaml.safe_load(cfg.read_text()) if cfg.exists() else {};"
            "data=data or {};"
            "servers=data.setdefault('mcp_servers', {});"
            f"name={name!r};"
            f"spec=json.loads({spec_json!r});"
            "sys.exit(2) if name in servers else None;"
            "servers[name]=spec[name];"
            "cfg.write_text(yaml.safe_dump(data, sort_keys=False))"
        )

        # Step 1: backup first (cp is a no-op if source missing — guard with test -f).
        backup_cmd = self._wsl_cmd(
            f"test -f '{self.hermes_config_wsl}' && "
            f"cp '{self.hermes_config_wsl}' '{backup_path}' || true"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *backup_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(proc.communicate(), timeout=WSL_TIMEOUT_S)
        except (asyncio.TimeoutError, OSError) as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
                error=f"backup step failed: {exc}",
            )

        # Step 2: mutate via python3 heredoc.
        write_cmd = self._wsl_cmd(f"python3 -c {self._shquote(script)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *write_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=WSL_TIMEOUT_S)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            rc = proc.returncode
        except (asyncio.TimeoutError, OSError) as exc:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path=backup_path,
                error=f"yaml-write step failed: {exc}",
            )

        if rc == 2:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=True,
                pre_apply_diff=f"# {name} already present in mcp_servers",
                post_apply_verification=(
                    f'python3 -c "import yaml;'
                    f"print('{name}' in (yaml.safe_load(open('{self.hermes_config_wsl}'))"
                    f".get('mcp_servers') or {{}}))\""
                ),
                rollback_path="",
                notes="idempotent skip",
            )

        if rc != 0:
            return ApplyResult(
                bookmark_id=entry.bookmark_id,
                success=False,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path=backup_path,
                error=f"python3 yaml-mutate failed (rc={rc}): {output[-500:]}",
            )

        return ApplyResult(
            bookmark_id=entry.bookmark_id,
            success=True,
            pre_apply_diff=(
                f"# Added to {self.hermes_config_wsl} under mcp_servers:\n"
                f"{json.dumps({name: server_block}, indent=2)}"
            ),
            post_apply_verification=(
                f'python3 -c "import yaml;'
                f"print('{name}' in (yaml.safe_load(open('{self.hermes_config_wsl}'))"
                f".get('mcp_servers') or {{}}))\""
            ),
            rollback_path=backup_path,
            notes="hermes config.yaml updated",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _wsl_cmd(bash_cmd: str) -> list[str]:
        return ["wsl.exe", "-d", "Ubuntu", "-u", "mattm", "-e", "bash", "-lc", bash_cmd]

    @staticmethod
    def _shquote(s: str) -> str:
        """POSIX single-quote a string for inclusion in a bash -lc argument."""
        return "'" + s.replace("'", "'\"'\"'") + "'"
