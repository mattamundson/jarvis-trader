"""Tests for the ConfigPatcher applier.

All subprocess calls are mocked — the real ~/.hermes/config.yaml is never read.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from discord.hermes_upgrade.appliers import config_patcher as cp_module
from discord.hermes_upgrade.appliers.config_patcher import (
    HERMES_CONFIG_WSL_DEFAULT,
    ConfigPatcher,
    _coerce_value,
)
from discord.hermes_upgrade.models import ApplyResult, BacklogEntry, UpgradeType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    bookmark_id: str = "cfg1",
    *,
    upgrade_type: UpgradeType = "config_improvement",
    implementation_steps: list[str] | None = None,
    rationale: str = "switch backend",
    notes: str = "",
) -> BacklogEntry:
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url=f"https://x.com/test/{bookmark_id}",
        source_discord_url=f"https://discord.com/channels/0/0/{bookmark_id}",
        source_vault_path=f"vault/{bookmark_id}.md",
        upgrade_type=upgrade_type,
        title="Test entry",
        rationale=rationale,
        implementation_steps=implementation_steps or ["model.provider: anthropic"],
        leverage_rank=4,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content="",
        notes=notes,
        tier="tier_1",
        apply_status="pending",
    )


class _FakeProc:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:  # noqa: A002
        return self._stdout, b""


def _make_subproc_mock(*, returncode: int = 0, stdout: bytes = b"") -> AsyncMock:
    fake = _FakeProc(returncode=returncode, stdout=stdout)
    return AsyncMock(return_value=fake)


# ---------------------------------------------------------------------------
# _coerce_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("anthropic", "anthropic"),
        ("true", True),
        ("False", False),
        ("yes", True),
        ("no", False),
        ("null", None),
        ("42", 42),
        ("3.14", 3.14),
        ('"https://api.anthropic.com"', "https://api.anthropic.com"),
        ("'quoted'", "quoted"),
        ("[1, 2, 3]", [1, 2, 3]),
    ],
)
def test_coerce_value(raw: str, expected: Any) -> None:
    assert _coerce_value(raw) == expected


# ---------------------------------------------------------------------------
# _extract_config_change
# ---------------------------------------------------------------------------


def test_extract_change_key_value_shape() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_with_bullet_prefix() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["- fallback_model.base_url: https://api.example.com"])
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "fallback_model.base_url"
    assert chg["new_value"] == "https://api.example.com"


def test_extract_change_boolean_coercion() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["features.enable_redact_secrets: true"])
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "features.enable_redact_secrets"
    assert chg["new_value"] is True


def test_extract_change_set_to_shape() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["Set model.provider to anthropic."])
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_returns_none_when_no_match() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["just narrative text with no key/value"])
    assert cp._extract_config_change(entry) is None


def test_extract_change_preserves_rationale_as_reason() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["model.provider: anthropic"],
        rationale="provider=auto trap (see feedback_hermes_provider_auto_trap.md)",
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert "provider=auto trap" in chg["reason"]


# ---------------------------------------------------------------------------
# Broadened parsers — change/switch/update natural-language shapes
# ---------------------------------------------------------------------------


def test_extract_change_with_change_keyword() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["Change model.provider to anthropic in the config."],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_with_switch_keyword() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=[
            "Switch model.provider in ~/.hermes/config.yaml from ollama to anthropic."
        ],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_with_update_keyword() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=[
            "Update fallback_model.base_url to https://generativelanguage.googleapis.com/v1beta/openai/"
        ],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "fallback_model.base_url"
    assert "generativelanguage" in str(chg["new_value"])


def test_extract_change_from_a_to_b_shape() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["Change model.provider from ollama to anthropic in config.yaml."],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_value_at_key() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["Set the value 'haiku' at model.default for cost optimization."],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    # Either SET_RE or AT_KEY_RE should match. The set/change form has priority.
    assert chg["key_path"] in ("model.default",)


def test_extract_change_from_extracted_content() -> None:
    """Implementation steps narrative; the actual key:value lives in extracted_content."""
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["Apply the recommended config change from the source."],
        notes="Per upstream guide:",
    )
    entry.extracted_content = "model.provider: anthropic"
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


# ---------------------------------------------------------------------------
# Bail-outs — .env target and ENV_VAR lines
# ---------------------------------------------------------------------------


def test_extract_change_bails_on_engine_dotenv_target() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=[
            "Add HERMES_HOME to engine/.env pointing at the new install path",
            "model.provider: anthropic",  # Would otherwise match.
        ],
    )
    assert cp._extract_config_change(entry) is None


def test_extract_change_bails_on_generic_dotenv_file_mention() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["Add TELEGRAM_BOT_TOKEN to the .env file for the profile"],
    )
    assert cp._extract_config_change(entry) is None


def test_extract_change_bails_on_env_var_only_line() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["TELEGRAM_BOT_TOKEN=abc123"],
    )
    assert cp._extract_config_change(entry) is None


def test_extract_change_quoted_value() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=['Set model.provider to "anthropic".'],
    )
    chg = cp._extract_config_change(entry)
    assert chg is not None
    assert chg["key_path"] == "model.provider"
    assert chg["new_value"] == "anthropic"


def test_extract_change_skips_hostname_false_positive() -> None:
    """Real backlog regression: 'config changes at github.com/Orchestra-Research/...'
    used to false-match as key=github.com, value=changes. Hostnames must be
    suppressed."""
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=[
            "Review PR #51 diff for Hermes CLI config changes at "
            "github.com/Orchestra-Research/AI-Research-SKILLs/pull/51",
        ],
    )
    assert cp._extract_config_change(entry) is None


def test_extract_change_skips_hostname_in_key_value_shape() -> None:
    """KEY_VALUE_RE could match `api.example.com: foo`; reject TLD terminals."""
    cp = ConfigPatcher()
    entry = _make_entry(
        implementation_steps=["See api.example.com: docs for the schema"],
    )
    assert cp._extract_config_change(entry) is None


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_renders_expected_block() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    out = await cp.dry_run(entry)
    assert HERMES_CONFIG_WSL_DEFAULT in out
    assert "model.provider" in out
    assert "anthropic" in out
    assert ".bak.<UTC-ts>" in out


@pytest.mark.asyncio
async def test_dry_run_error_when_no_change() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["narrative only"])
    out = await cp.dry_run(entry)
    assert "ERROR" in out
    assert entry.bookmark_id in out


# ---------------------------------------------------------------------------
# apply — happy path / idempotency / failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_round_trips_via_subprocess() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    # Simulate the python3 script printing OK on stdout, exit 0.
    mock_exec = _make_subproc_mock(
        returncode=0,
        stdout=b"OK old='openrouter' new='anthropic' backup=/tmp/cfg.bak backend=pyyaml\n",
    )
    with patch("asyncio.create_subprocess_exec", mock_exec):
        result = await cp.apply(entry)

    assert result.success is True
    assert "key=model.provider" in result.pre_apply_diff
    assert result.rollback_path.startswith("cp ")
    assert HERMES_CONFIG_WSL_DEFAULT in result.rollback_path
    # The grep verification mentions the leaf key.
    assert "provider" in result.post_apply_verification


@pytest.mark.asyncio
async def test_apply_idempotent_skip_on_rc3() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    # rc=3 means the script detected current value == new value.
    mock_exec = _make_subproc_mock(returncode=3, stdout=b"")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        result = await cp.apply(entry)

    assert result.success is True
    assert "idempotent skip" in (result.notes or "")
    assert result.rollback_path == ""  # no backup needed for a skip


@pytest.mark.asyncio
async def test_apply_failure_on_nonzero_rc() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    mock_exec = _make_subproc_mock(returncode=1, stdout=b"ImportError: no yaml\n")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        result = await cp.apply(entry)
    assert result.success is False
    assert result.error is not None
    assert "yaml-mutate failed" in result.error


@pytest.mark.asyncio
async def test_apply_returns_error_when_no_change_extractable() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["narrative only"])
    result = await cp.apply(entry)
    assert result.success is False
    assert "could not parse config change" in (result.error or "")


@pytest.mark.asyncio
async def test_apply_failure_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])

    async def _raise_timeout(*_a: Any, **_kw: Any) -> Any:
        raise TimeoutError()

    with (
        patch("asyncio.create_subprocess_exec", _make_subproc_mock()),
        patch.object(cp_module.asyncio, "wait_for", _raise_timeout),
    ):
        result = await cp.apply(entry)

    assert result.success is False
    assert "timed out" in (result.error or "")


# ---------------------------------------------------------------------------
# Patch script construction
# ---------------------------------------------------------------------------


def test_build_patch_script_contains_required_pieces() -> None:
    cp = ConfigPatcher()
    script = cp._build_patch_script(
        cfg_path="/home/mattm/.hermes/config.yaml",
        backup_path="/home/mattm/.hermes/config.yaml.bak.20260520T120000Z",
        key_path="model.provider",
        new_value="anthropic",
    )
    # Has both YAML backends + dotted-path walker + idempotent exit code.
    assert "ruamel.yaml" in script
    assert "yaml as _yaml" in script
    assert "shutil.copy(p, backup)" in script
    assert "sys.exit(3)" in script
    # The literal values are passed through repr().
    assert "'model.provider'" in script
    assert "anthropic" in script


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_true_when_subprocess_prints_match() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    mock_exec = _make_subproc_mock(returncode=0, stdout=b"MATCH\n")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        ok = await cp.verify(
            entry,
            ApplyResult(
                bookmark_id="cfg1",
                success=True,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
            ),
        )
    assert ok is True


@pytest.mark.asyncio
async def test_verify_false_when_subprocess_prints_differ() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["model.provider: anthropic"])
    mock_exec = _make_subproc_mock(returncode=0, stdout=b"DIFFER\n")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        ok = await cp.verify(
            entry,
            ApplyResult(
                bookmark_id="cfg1",
                success=True,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
            ),
        )
    assert ok is False


@pytest.mark.asyncio
async def test_verify_false_when_no_change() -> None:
    cp = ConfigPatcher()
    entry = _make_entry(implementation_steps=["narrative only"])
    ok = await cp.verify(
        entry,
        ApplyResult(
            bookmark_id="cfg1",
            success=True,
            pre_apply_diff="",
            post_apply_verification="",
            rollback_path="",
        ),
    )
    assert ok is False


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_runs_restore_command() -> None:
    cp = ConfigPatcher()
    entry = _make_entry()
    result = ApplyResult(
        bookmark_id="cfg1",
        success=True,
        pre_apply_diff="",
        post_apply_verification="",
        rollback_path="cp /home/mattm/.hermes/config.yaml.bak.20260520T120000Z "
        "/home/mattm/.hermes/config.yaml",
    )
    mock_exec = _make_subproc_mock(returncode=0)
    with patch("asyncio.create_subprocess_exec", mock_exec):
        assert await cp.rollback(entry, result) is True
    mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_rollback_returns_false_when_no_path() -> None:
    cp = ConfigPatcher()
    result = ApplyResult(
        bookmark_id="cfg1",
        success=True,
        pre_apply_diff="",
        post_apply_verification="",
        rollback_path="",
    )
    assert await cp.rollback(_make_entry(), result) is False
