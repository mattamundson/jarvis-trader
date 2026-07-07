"""Tests for the LibraryIntegrator applier.

All subprocess calls are mocked — no real venvs, no real wsl.exe invocations.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from discord.hermes_upgrade.appliers import library_integrator as li_module
from discord.hermes_upgrade.appliers.library_integrator import (
    GEPA_VENV_PIP,
    HERMES_VENV_PIP,
    LibraryIntegrator,
    _pkg_root,
)
from discord.hermes_upgrade.models import ApplyResult, BacklogEntry, UpgradeType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_UNSET: list[str] = ["pip install foo"]


def _make_entry(
    bookmark_id: str = "lib1",
    *,
    upgrade_type: UpgradeType = "library",
    implementation_steps: list[str] | None = _UNSET,
    notes: str = "",
    extracted_content: str = "",
    title: str = "Test entry",
) -> BacklogEntry:
    steps = _UNSET if implementation_steps is _UNSET else implementation_steps
    if steps is _UNSET:
        steps = ["pip install foo"]
    return BacklogEntry(
        bookmark_id=bookmark_id,
        source_bookmark_url=f"https://x.com/test/{bookmark_id}",
        source_discord_url=f"https://discord.com/channels/0/0/{bookmark_id}",
        source_vault_path=f"vault/{bookmark_id}.md",
        upgrade_type=upgrade_type,
        title=title,
        rationale="because tests",
        implementation_steps=steps,
        leverage_rank=4,
        risk="low",
        dependencies=[],
        estimated_cost_usd=0.0,
        extracted_content=extracted_content,
        notes=notes,
        tier="tier_1",
        apply_status="pending",
    )


class _FakeProc:
    """Minimal asyncio.subprocess.Process double."""

    def __init__(self, *, returncode: int = 0, stdout: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:  # noqa: A002
        return self._stdout, b""


def _make_subproc_mock(
    *,
    returncode: int = 0,
    stdout: bytes = b"",
) -> AsyncMock:
    """Build an AsyncMock suitable for replacing ``asyncio.create_subprocess_exec``."""
    fake = _FakeProc(returncode=returncode, stdout=stdout)
    mock = AsyncMock(return_value=fake)
    return mock


# ---------------------------------------------------------------------------
# _pkg_root helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("foo", "foo"),
        ("foo==1.2.3", "foo"),
        ("foo[extra]", "foo"),
        ("foo[extra,more]==2.0", "foo"),
        ("foo-bar", "foo-bar"),
        ("foo_bar.baz", "foo_bar.baz"),
        ("foo>=1.0,<2.0", "foo"),
    ],
)
def test_pkg_root(spec: str, expected: str) -> None:
    assert _pkg_root(spec) == expected


# ---------------------------------------------------------------------------
# _extract_pip_spec
# ---------------------------------------------------------------------------


def test_extract_pip_spec_simple() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install foo"])
    assert li._extract_pip_spec(entry) == ("hermes", "foo")


def test_extract_pip_spec_with_version() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["Run: pip install foo==1.2.3"])
    assert li._extract_pip_spec(entry) == ("hermes", "foo==1.2.3")


def test_extract_pip_spec_with_extras() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install foo[extra,more]"])
    assert li._extract_pip_spec(entry) == ("hermes", "foo[extra,more]")


def test_extract_pip_spec_gepa_routing_via_notes() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install dspy"],
        notes="install into the GEPA venv",
    )
    assert li._extract_pip_spec(entry) == ("gepa", "dspy")


def test_extract_pip_spec_gepa_routing_via_self_evolution_keyword() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install dspy"],
        extracted_content="for hermes-agent-self-evolution",
    )
    assert li._extract_pip_spec(entry) == ("gepa", "dspy")


def test_extract_pip_spec_returns_none_when_no_pip_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["just do something else"])
    assert li._extract_pip_spec(entry) is None


def test_extract_pip_spec_returns_none_for_empty_steps() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=[])
    assert li._extract_pip_spec(entry) is None


# ---------------------------------------------------------------------------
# _extract_pip_spec — broadened LLM-output patterns
# ---------------------------------------------------------------------------


def test_extract_pip_spec_uv_add() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["Install via uv add langchain"])
    assert li._extract_pip_spec(entry) == ("hermes", "langchain")


def test_extract_pip_spec_uv_pip_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["uv pip install openai==1.42.0"])
    assert li._extract_pip_spec(entry) == ("hermes", "openai==1.42.0")


def test_extract_pip_spec_requirements_file() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=[
            "Clone the repo",
            "pip install -r requirements.txt from the cloned repo",
        ],
    )
    assert li._extract_pip_spec(entry) == ("hermes", "-r requirements.txt")


def test_extract_pip_spec_editable_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install -e /home/mattm/Code/some-lib"],
    )
    assert li._extract_pip_spec(entry) == ("hermes", "-e /home/mattm/Code/some-lib")


def test_extract_pip_spec_github_clone_plus_pip_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=[
            "git clone https://github.com/openai/whisper.git and then pip install .",
        ],
    )
    spec = li._extract_pip_spec(entry)
    assert spec is not None
    target, pkg = spec
    assert pkg.startswith("git+https://github.com/openai/whisper")


def test_extract_pip_spec_install_prose_with_python_hint() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        title="LangGraph workflow library",
        implementation_steps=["Install langgraph"],
        notes="This Python library powers agent state machines.",
    )
    assert li._extract_pip_spec(entry) == ("hermes", "langgraph")


def test_extract_pip_spec_title_derived_libname_pattern() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        title="langchain: LLM orchestration framework",
        implementation_steps=["Read the docs"],
        extracted_content="A popular Python library for chaining LLM calls.",
    )
    assert li._extract_pip_spec(entry) == ("hermes", "langchain")


def test_extract_pip_spec_gepa_routing_from_extracted_content_only() -> None:
    """target_venv inferred from extracted_content (not just steps/notes)."""
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["uv add dspy"],
        extracted_content="Wire into the GEPA optimization loop for evolved prompts.",
    )
    assert li._extract_pip_spec(entry) == ("gepa", "dspy")


def test_extract_pip_spec_gepa_routing_from_title_only() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install dspy"],
        title="GEPA-friendly: dspy",
    )
    assert li._extract_pip_spec(entry) == ("gepa", "dspy")


def test_extract_pip_spec_finds_pip_install_in_extracted_content() -> None:
    """Scan extracted_content + notes for pip install, not just steps."""
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["Read the upstream docs."],
        extracted_content="Then run: pip install quantstats==0.0.62",
    )
    assert li._extract_pip_spec(entry) == ("hermes", "quantstats==0.0.62")


# ---------------------------------------------------------------------------
# apply — requirements / editable specs use flag+arg shape (no quoted blob)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_with_requirements_file_uses_flag_arg_shape() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install -r requirements.txt"],
    )
    mock_exec = _make_subproc_mock(returncode=0)
    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", mock_exec),
    ):
        result = await li.apply(entry)
    assert result.success is True
    bash_cmd = mock_exec.call_args.args[-1]
    # `-r requirements.txt` must appear as a flag + quoted path, NOT as a
    # single quoted token "'-r requirements.txt'" (which pip would reject).
    assert " -r requirements.txt" in bash_cmd
    assert "'-r requirements.txt'" not in bash_cmd


@pytest.mark.asyncio
async def test_apply_with_editable_install_uses_flag_arg_shape() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install -e /home/mattm/Code/foo"],
    )
    mock_exec = _make_subproc_mock(returncode=0)
    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", mock_exec),
    ):
        result = await li.apply(entry)
    assert result.success is True
    bash_cmd = mock_exec.call_args.args[-1]
    assert " -e /home/mattm/Code/foo" in bash_cmd


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_hermes_target() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install dspy==2.4.0"])
    out = await li.dry_run(entry)
    assert "target_venv=hermes" in out
    assert HERMES_VENV_PIP in out
    assert "dspy==2.4.0" in out
    assert "dspy" in out  # verify line


@pytest.mark.asyncio
async def test_dry_run_gepa_target() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install dspy"],
        notes="for gepa optimization run",
    )
    out = await li.dry_run(entry)
    assert "target_venv=gepa" in out
    assert GEPA_VENV_PIP in out


@pytest.mark.asyncio
async def test_dry_run_returns_error_when_no_spec() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["no pip here"])
    out = await li.dry_run(entry)
    assert "ERROR" in out
    assert entry.bookmark_id in out


# ---------------------------------------------------------------------------
# apply — idempotency short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_short_circuits_when_installed() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install foo==1.0"])

    with patch.object(li, "_is_installed", AsyncMock(return_value=True)):
        result = await li.apply(entry)

    assert result.success is True
    assert "idempotent skip" in (result.notes or "")
    assert "already installed" in result.pre_apply_diff
    assert "uninstall -y foo" in result.rollback_path


@pytest.mark.asyncio
async def test_apply_returns_error_when_no_pip_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["nothing actionable here"])
    result = await li.apply(entry)
    assert result.success is False
    assert "could not parse pip install spec" in (result.error or "")


# ---------------------------------------------------------------------------
# apply — subprocess wiring (success + failure paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_invokes_hermes_pip_bin_on_install() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install dspy==1.0"])

    mock_exec = _make_subproc_mock(returncode=0, stdout=b"Successfully installed dspy-1.0\n")

    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", mock_exec),
    ):
        result = await li.apply(entry)

    assert result.success is True
    # Verify the wsl.exe invocation contained the hermes pip path.
    called_args, _called_kwargs = mock_exec.call_args
    bash_cmd = called_args[-1]
    assert HERMES_VENV_PIP in bash_cmd
    assert "dspy==1.0" in bash_cmd
    assert result.rollback_path == f"{HERMES_VENV_PIP} uninstall -y dspy"


@pytest.mark.asyncio
async def test_apply_invokes_gepa_pip_bin_when_routed() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(
        implementation_steps=["pip install dspy"],
        notes="for self-evolution loop",
    )

    mock_exec = _make_subproc_mock(returncode=0, stdout=b"")

    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", mock_exec),
    ):
        result = await li.apply(entry)

    assert result.success is True
    called_args, _called_kwargs = mock_exec.call_args
    bash_cmd = called_args[-1]
    assert GEPA_VENV_PIP in bash_cmd


@pytest.mark.asyncio
async def test_apply_returns_failure_on_nonzero_exit() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install bogus-pkg"])
    mock_exec = _make_subproc_mock(returncode=1, stdout=b"ERROR: No matching distribution\n")

    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", mock_exec),
    ):
        result = await li.apply(entry)

    assert result.success is False
    assert result.error is not None
    assert "non-zero exit" in result.error


@pytest.mark.asyncio
async def test_apply_returns_failure_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install foo"])

    async def _raise_timeout(*_a: Any, **_kw: Any) -> Any:
        raise TimeoutError()

    with (
        patch.object(li, "_is_installed", AsyncMock(return_value=False)),
        patch.object(li_module.asyncio, "wait_for", _raise_timeout),
        patch("asyncio.create_subprocess_exec", _make_subproc_mock()),
    ):
        result = await li.apply(entry)

    assert result.success is False
    assert "timed out" in (result.error or "")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_returns_true_when_installed() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["pip install foo"])
    with patch.object(li, "_is_installed", AsyncMock(return_value=True)):
        ok = await li.verify(
            entry,
            ApplyResult(
                bookmark_id="lib1",
                success=True,
                pre_apply_diff="",
                post_apply_verification="",
                rollback_path="",
            ),
        )
    assert ok is True


@pytest.mark.asyncio
async def test_verify_returns_false_when_no_spec() -> None:
    li = LibraryIntegrator()
    entry = _make_entry(implementation_steps=["nothing"])
    ok = await li.verify(
        entry,
        ApplyResult(
            bookmark_id="lib1",
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
async def test_rollback_invokes_subprocess_when_path_set() -> None:
    li = LibraryIntegrator()
    entry = _make_entry()
    result = ApplyResult(
        bookmark_id="lib1",
        success=True,
        pre_apply_diff="",
        post_apply_verification="",
        rollback_path=f"{HERMES_VENV_PIP} uninstall -y foo",
    )
    mock_exec = _make_subproc_mock(returncode=0)
    with patch("asyncio.create_subprocess_exec", mock_exec):
        assert await li.rollback(entry, result) is True
    mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_rollback_returns_false_when_no_path() -> None:
    li = LibraryIntegrator()
    entry = _make_entry()
    result = ApplyResult(
        bookmark_id="lib1",
        success=True,
        pre_apply_diff="",
        post_apply_verification="",
        rollback_path="",
    )
    assert await li.rollback(entry, result) is False


# ---------------------------------------------------------------------------
# _is_installed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_installed_true_when_pip_show_returns_name_line() -> None:
    li = LibraryIntegrator()
    mock_exec = _make_subproc_mock(returncode=0, stdout=b"Name: foo\nVersion: 1.0\n")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        assert await li._is_installed(HERMES_VENV_PIP, "foo") is True


@pytest.mark.asyncio
async def test_is_installed_false_when_pip_show_empty() -> None:
    li = LibraryIntegrator()
    mock_exec = _make_subproc_mock(returncode=1, stdout=b"")
    with patch("asyncio.create_subprocess_exec", mock_exec):
        assert await li._is_installed(HERMES_VENV_PIP, "foo") is False
