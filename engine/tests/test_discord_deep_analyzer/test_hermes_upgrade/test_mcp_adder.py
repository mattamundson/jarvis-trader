"""Tests for engine.discord.hermes_upgrade.appliers.mcp_adder."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from discord.hermes_upgrade.appliers.mcp_adder import McpAdder
from discord.hermes_upgrade.models import BacklogEntry


def _entry(
    *,
    bookmark_id: str = "bm-mcp-1",
    implementation_steps: list[str] | None = None,
    notes: str = "",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url="https://x.com/foo/status/1",
        source_discord_url="https://discord.com/channels/1/2/3",
        source_vault_path="raw/x-bookmarks/2026-W21.md",
        upgrade_type="mcp_server",
        title="add discord-jarvis mcp",
        rationale="r",
        implementation_steps=implementation_steps or [],
        leverage_rank=4,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content="",
        notes=notes,
        tier="tier_1",
    )


# ---------------------------------------------------------------------------
# _parse_mcp_spec
# ---------------------------------------------------------------------------


def test_parse_spec_basic():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "name: discord-jarvis",
            "command: /usr/bin/python3",
            'args: ["mcp_server.py"]',
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "discord-jarvis"
    assert spec["command"] == "/usr/bin/python3"
    assert spec["args"] == ["mcp_server.py"]
    assert "env" not in spec


def test_parse_spec_with_bullet_prefixes():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "- name: my-server",
            "- command: node",
            '- args: ["index.js"]',
            '- env: {"DEBUG": "1"}',
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "my-server"
    assert spec["command"] == "node"
    assert spec["args"] == ["index.js"]
    assert spec["env"] == {"DEBUG": "1"}


def test_parse_spec_with_windows_command_path():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "name: foo",
            r"command: C:\Users\mattm\python.exe",
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["command"] == r"C:\Users\mattm\python.exe"


def test_parse_spec_returns_none_when_missing_name():
    adder = McpAdder()
    entry = _entry(implementation_steps=["command: /usr/bin/python3"])
    assert adder._parse_mcp_spec(entry) is None


def test_parse_spec_returns_none_when_missing_command():
    adder = McpAdder()
    entry = _entry(implementation_steps=["name: foo"])
    assert adder._parse_mcp_spec(entry) is None


def test_parse_spec_returns_none_when_no_steps():
    adder = McpAdder()
    entry = _entry(implementation_steps=[])
    assert adder._parse_mcp_spec(entry) is None


def test_parse_spec_ignores_args_when_not_a_list():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "name: foo",
            "command: bar",
            "args: not a list",
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert "args" not in spec


# ---------------------------------------------------------------------------
# _target_is_claude_code routing
# ---------------------------------------------------------------------------


def test_routes_to_claude_code_when_claude_json_mentioned():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["Add to ~/.claude.json mcpServers"],
    )
    assert adder._target_is_claude_code(entry) is True


def test_routes_to_claude_code_when_claude_code_mentioned():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["This is for Claude Code"],
        notes="",
    )
    assert adder._target_is_claude_code(entry) is True


def test_routes_to_hermes_yaml_by_default():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "name: foo",
            "command: bar",
        ]
    )
    assert adder._target_is_claude_code(entry) is False


def test_routes_via_notes_field():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["name: foo", "command: bar"],
        notes="Add to claude.json",
    )
    assert adder._target_is_claude_code(entry) is True


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


async def test_dry_run_claude_code_target():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Target: ~/.claude.json",
            "name: discord-jarvis",
            "command: /usr/bin/python3",
        ]
    )
    out = await adder.dry_run(entry)
    assert "claude.json" in out
    assert "mcpServers" in out
    assert "discord-jarvis" in out


async def test_dry_run_hermes_target():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "name: discord-jarvis",
            "command: /usr/bin/python3",
        ]
    )
    out = await adder.dry_run(entry)
    assert "hermes/config.yaml" in out
    assert "mcp_servers" in out


async def test_dry_run_error_on_bad_spec():
    adder = McpAdder()
    entry = _entry(implementation_steps=[])
    out = await adder.dry_run(entry)
    assert out.startswith("ERROR")


# ---------------------------------------------------------------------------
# apply -> claude.json
# ---------------------------------------------------------------------------


async def test_apply_claude_json_adds_new_entry(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "old"}}}),
        encoding="utf-8",
    )
    adder = McpAdder(claude_json_path=fake_claude)

    entry = _entry(
        implementation_steps=[
            "Add to ~/.claude.json",
            "name: discord-jarvis",
            "command: /usr/bin/python3",
            'args: ["mcp_server.py"]',
        ]
    )

    result = await adder.apply(entry)

    assert result.success is True
    assert result.rollback_path  # backup created
    backup = Path(result.rollback_path)
    assert backup.exists()
    assert ".bak." in backup.name

    data = json.loads(fake_claude.read_text(encoding="utf-8"))
    assert "discord-jarvis" in data["mcpServers"]
    assert data["mcpServers"]["discord-jarvis"]["command"] == "/usr/bin/python3"
    assert data["mcpServers"]["discord-jarvis"]["args"] == ["mcp_server.py"]
    # Pre-existing entry preserved
    assert "existing" in data["mcpServers"]


async def test_apply_claude_json_idempotent(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {"discord-jarvis": {"command": "/usr/bin/python3"}}}),
        encoding="utf-8",
    )
    adder = McpAdder(claude_json_path=fake_claude)

    entry = _entry(
        implementation_steps=[
            "Target ~/.claude.json",
            "name: discord-jarvis",
            "command: /usr/bin/python3",
        ]
    )

    result = await adder.apply(entry)
    assert result.success is True
    assert result.notes == "idempotent skip"
    # No backup created on idempotent path
    assert result.rollback_path == ""


async def test_apply_claude_json_creates_mcp_servers_when_missing(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(json.dumps({"other": "field"}), encoding="utf-8")
    adder = McpAdder(claude_json_path=fake_claude)

    entry = _entry(
        implementation_steps=[
            "Target ~/.claude.json",
            "name: foo",
            "command: bar",
        ]
    )

    result = await adder.apply(entry)
    assert result.success is True
    data = json.loads(fake_claude.read_text(encoding="utf-8"))
    assert data["mcpServers"]["foo"]["command"] == "bar"
    assert data["other"] == "field"


async def test_apply_claude_json_missing_file_returns_error(tmp_path: Path):
    fake_claude = tmp_path / "does-not-exist.json"
    adder = McpAdder(claude_json_path=fake_claude)

    entry = _entry(
        implementation_steps=[
            "Add to ~/.claude.json",
            "name: foo",
            "command: bar",
        ]
    )
    result = await adder.apply(entry)
    assert result.success is False
    assert result.error is not None and "not found" in result.error


async def test_apply_returns_error_on_unparseable_spec():
    adder = McpAdder()
    entry = _entry(implementation_steps=["nothing structured"])
    result = await adder.apply(entry)
    assert result.success is False
    assert result.error is not None and "could not parse" in result.error


# ---------------------------------------------------------------------------
# apply -> hermes yaml (WSL-side, mocked)
# ---------------------------------------------------------------------------


async def test_apply_hermes_yaml_invokes_wsl(tmp_path: Path):
    adder = McpAdder(hermes_config_wsl="/home/mattm/.hermes/config.yaml")
    entry = _entry(
        implementation_steps=[
            "name: my-server",
            "command: /usr/bin/node",
            'args: ["server.js"]',
        ]
    )

    # Two subprocess calls: backup then mutate. Both return rc=0.
    backup_proc = MagicMock()
    backup_proc.returncode = 0
    backup_proc.communicate = AsyncMock(return_value=(b"", b""))

    mutate_proc = MagicMock()
    mutate_proc.returncode = 0
    mutate_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch(
        "discord.hermes_upgrade.appliers.mcp_adder.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[backup_proc, mutate_proc]),
    ) as mock_exec:
        result = await adder.apply(entry)

    assert result.success is True
    assert ".bak." in result.rollback_path

    # First call should be the backup (cp).
    call0_args, _ = mock_exec.call_args_list[0]
    assert call0_args[0] == "wsl.exe"
    assert "cp" in call0_args[-1]
    assert ".bak." in call0_args[-1]

    # Second call should be the python3 yaml-mutate.
    call1_args, _ = mock_exec.call_args_list[1]
    assert "python3 -c" in call1_args[-1]
    assert "yaml.safe_load" in call1_args[-1]
    assert "my-server" in call1_args[-1]


async def test_apply_hermes_yaml_idempotent_skip():
    adder = McpAdder(hermes_config_wsl="/home/mattm/.hermes/config.yaml")
    entry = _entry(
        implementation_steps=[
            "name: my-server",
            "command: /usr/bin/node",
        ]
    )

    backup_proc = MagicMock()
    backup_proc.returncode = 0
    backup_proc.communicate = AsyncMock(return_value=(b"", b""))

    mutate_proc = MagicMock()
    # rc=2 = idempotent-skip sentinel from the python heredoc
    mutate_proc.returncode = 2
    mutate_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch(
        "discord.hermes_upgrade.appliers.mcp_adder.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[backup_proc, mutate_proc]),
    ):
        result = await adder.apply(entry)

    assert result.success is True
    assert result.notes == "idempotent skip"


async def test_apply_hermes_yaml_failure_returns_error():
    adder = McpAdder(hermes_config_wsl="/home/mattm/.hermes/config.yaml")
    entry = _entry(
        implementation_steps=[
            "name: bad",
            "command: /usr/bin/false",
        ]
    )

    backup_proc = MagicMock()
    backup_proc.returncode = 0
    backup_proc.communicate = AsyncMock(return_value=(b"", b""))

    mutate_proc = MagicMock()
    mutate_proc.returncode = 1
    mutate_proc.communicate = AsyncMock(
        return_value=(b"Traceback: yaml parse error\n", b""),
    )

    with patch(
        "discord.hermes_upgrade.appliers.mcp_adder.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[backup_proc, mutate_proc]),
    ):
        result = await adder.apply(entry)

    assert result.success is False
    assert result.error is not None and "rc=1" in result.error


# ---------------------------------------------------------------------------
# verify (claude.json path)
# ---------------------------------------------------------------------------


async def test_verify_claude_json_true_when_present(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {"foo": {"command": "bar"}}}),
        encoding="utf-8",
    )
    adder = McpAdder(claude_json_path=fake_claude)
    entry = _entry(
        implementation_steps=[
            "Target ~/.claude.json",
            "name: foo",
            "command: bar",
        ]
    )
    ok = await adder.verify(entry, MagicMock())
    assert ok is True


async def test_verify_claude_json_false_when_missing(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {"other": {}}}),
        encoding="utf-8",
    )
    adder = McpAdder(claude_json_path=fake_claude)
    entry = _entry(
        implementation_steps=[
            "Target ~/.claude.json",
            "name: foo",
            "command: bar",
        ]
    )
    ok = await adder.verify(entry, MagicMock())
    assert ok is False


# ---------------------------------------------------------------------------
# rollback (claude.json path)
# ---------------------------------------------------------------------------


async def test_rollback_claude_json_restores_backup(tmp_path: Path):
    fake_claude = tmp_path / ".claude.json"
    backup = tmp_path / ".claude.json.bak.20260520T120000Z"
    original = {"mcpServers": {"original": {"command": "x"}}}
    mutated = {"mcpServers": {"original": {"command": "x"}, "added": {"command": "y"}}}
    backup.write_text(json.dumps(original), encoding="utf-8")
    fake_claude.write_text(json.dumps(mutated), encoding="utf-8")

    adder = McpAdder(claude_json_path=fake_claude)
    entry = _entry(
        implementation_steps=["Target ~/.claude.json", "name: added", "command: y"],
    )
    result = MagicMock()
    result.rollback_path = str(backup)

    ok = await adder.rollback(entry, result)
    assert ok is True
    restored = json.loads(fake_claude.read_text(encoding="utf-8"))
    assert restored == original


async def test_rollback_false_when_no_backup_path():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["Target ~/.claude.json", "name: foo", "command: bar"],
    )
    result = MagicMock()
    result.rollback_path = ""
    ok = await adder.rollback(entry, result)
    assert ok is False


# ---------------------------------------------------------------------------
# Broadened parser — JSON fence
# ---------------------------------------------------------------------------


def test_parse_spec_from_json_fence():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Add the following block to ~/.claude.json:",
            '```json\n{"name": "x-mcp", "command": "npx", "args": ["-y", "x-mcp"]}\n```',
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "x-mcp"
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", "x-mcp"]
    assert spec["_target"] == "claude_json"
    assert spec.get("_human_required") is not True


def test_parse_spec_from_json_fence_mcp_servers_shape():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Edit ~/.hermes/config.yaml and add:",
            '```\n{"mcpServers": {"foo": {"command": "node", "args": ["foo.js"]}}}\n```',
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "foo"
    assert spec["command"] == "node"
    assert spec["args"] == ["foo.js"]


# ---------------------------------------------------------------------------
# Broadened parser — GitHub repo + MCP
# ---------------------------------------------------------------------------


def test_parse_spec_from_github_url_with_mcp_keyword():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Clone https://github.com/rohitg00/agentmemory to /home/mattm/.hermes/mcp-servers/agentmemory",
            "Configure as an MCP server in Hermes config",
        ],
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "agentmemory"
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", "https://github.com/rohitg00/agentmemory"]
    assert spec["_human_required"] is True


def test_parse_spec_from_github_url_no_mcp_keyword_returns_none():
    adder = McpAdder()
    # No MCP-keyword in haystack -> github URL alone isn't enough.
    entry = _entry(
        implementation_steps=["Clone https://github.com/foo/bar for reference"],
    )
    assert adder._parse_mcp_spec(entry) is None


# ---------------------------------------------------------------------------
# Broadened parser — npm/npx
# ---------------------------------------------------------------------------


def test_parse_spec_from_npm_install():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Install the X.com MCP via npm install -g x-mcp-server",
            "Then register it in claude.json",
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "x-mcp-server"
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", "x-mcp-server"]
    assert spec["_target"] == "claude_json"
    assert spec["_human_required"] is True


def test_parse_spec_from_npx():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["Run npx @modelcontextprotocol/server-foo to register the MCP server"]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "server-foo"
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", "@modelcontextprotocol/server-foo"]


# ---------------------------------------------------------------------------
# Broadened parser — python -m
# ---------------------------------------------------------------------------


def test_parse_spec_from_python_module():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Run python -m hermes_webui to start the MCP server",
        ]
    )
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["name"] == "hermes_webui"
    assert spec["command"] == "python"
    assert spec["args"] == ["-m", "hermes_webui"]


# ---------------------------------------------------------------------------
# Broadened parser — URL-only fallback
# ---------------------------------------------------------------------------


def test_parse_spec_url_only_fallback():
    adder = McpAdder()
    entry = _entry(
        bookmark_id="bm-url-only",
        implementation_steps=[
            "See https://example.com/hermes-hud for the MCP server release notes",
        ],
    )
    # Title-derived slug.
    spec = adder._parse_mcp_spec(entry)
    assert spec is not None
    assert spec["command"] == "echo"
    assert spec["args"] == ["https://example.com/hermes-hud"]
    assert spec["_human_required"] is True


def test_parse_spec_url_only_returns_none_without_mcp_keyword():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=["Visit https://example.com to read the article"],
    )
    assert adder._parse_mcp_spec(entry) is None


# ---------------------------------------------------------------------------
# Target detection — broadened heuristic
# ---------------------------------------------------------------------------


def test_resolve_target_claude_json_explicit():
    adder = McpAdder()
    entry = _entry(implementation_steps=["Register in ~/.claude.json under mcpServers"])
    assert adder._resolve_target(entry) == "claude_json"


def test_resolve_target_hermes_yaml_via_path():
    adder = McpAdder()
    entry = _entry(implementation_steps=["Add to /home/mattm/.hermes/config.yaml"])
    assert adder._resolve_target(entry) == "hermes_yaml"


def test_resolve_target_unknown_when_neither():
    adder = McpAdder()
    entry = _entry(implementation_steps=["Install something somewhere"])
    assert adder._resolve_target(entry) == "unknown"


def test_resolve_target_via_extracted_content():
    adder = McpAdder()
    # Notes/extracted_content should also count.
    entry = _entry(
        implementation_steps=["Configure the MCP server"],
        notes="Add this to claude.json",
    )
    assert adder._resolve_target(entry) == "claude_json"


# ---------------------------------------------------------------------------
# dry_run surfaces human_required flag
# ---------------------------------------------------------------------------


async def test_dry_run_human_required_warning():
    adder = McpAdder()
    entry = _entry(
        implementation_steps=[
            "Install via npm install -g foo-mcp",
            "Register it as an MCP server in ~/.claude.json",
        ]
    )
    out = await adder.dry_run(entry)
    assert "WARNING" in out
    assert "synthesized" in out.lower() or "best-guess" in out.lower()


async def test_apply_strips_private_keys_from_claude_json(tmp_path: Path):
    """Synthesized spec carries _human_required + _target; these must not
    leak into the written claude.json block."""
    fake_claude = tmp_path / ".claude.json"
    fake_claude.write_text(
        json.dumps({"mcpServers": {}}),
        encoding="utf-8",
    )
    adder = McpAdder(claude_json_path=fake_claude)
    entry = _entry(
        implementation_steps=[
            "Add to ~/.claude.json",
            "Install via npm install -g foo-mcp (an MCP server)",
        ]
    )
    result = await adder.apply(entry)
    assert result.success is True
    data = json.loads(fake_claude.read_text(encoding="utf-8"))
    block = data["mcpServers"]["foo-mcp"]
    assert block["command"] == "npx"
    assert block["args"] == ["-y", "foo-mcp"]
    assert "_human_required" not in block
    assert "_target" not in block


# pytest-asyncio auto mode handles the coroutines; no marker needed.
__all__: list[str] = []
