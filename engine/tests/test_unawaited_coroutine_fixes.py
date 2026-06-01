"""
Regression tests for 3 unawaited coroutine fixes (commit 5d584f1).

Bug history: prior to 2026-05-07 three coroutine calls were silently dropped:
  1. openclaw_router._send_reply: send_whatsapp_message was bare-called (not awaited)
  2. rolling_wfe_scheduler.send_alert: notifier.send was bare-called (not awaited)
  3. JarvisLLMClient.provider: no class-level default caused AttributeError before __init__

These tests ensure the fixes are not regressed.

Run:
    cd engine
    .venv/Scripts/python -m pytest tests/test_unawaited_coroutine_fixes.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Path setup
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))


# ---------------------------------------------------------------------------
# Fix 1: openclaw_router._send_reply uses asyncio.create_task (not bare call)
# ---------------------------------------------------------------------------


class TestOpenclawSendReplyCoroutine:
    """Verify _send_reply properly schedules the async send_whatsapp_message."""

    def test_send_reply_uses_create_task_inside_async_context(self):
        """
        When called from within a running event loop, _send_reply must schedule
        via asyncio.create_task — NOT call the coroutine bare.
        """
        create_task_calls = []
        mock_coro = AsyncMock(return_value=None)

        async def _mock_send_whatsapp(msg):
            return await mock_coro(msg)

        async def _run():
            with patch(
                "notifications.openclaw_notifier.send_whatsapp_message",
                side_effect=_mock_send_whatsapp,
            ):
                with patch("asyncio.get_running_loop") as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_loop.create_task = MagicMock(
                        side_effect=lambda coro: create_task_calls.append(coro)
                    )
                    mock_get_loop.return_value = mock_loop

                    from routers.openclaw_router import _send_reply

                    _send_reply("test message")

                    # Must have called create_task, not bare-invoked the coroutine
                    assert len(create_task_calls) == 1, (
                        "Expected exactly one asyncio.create_task call; "
                        f"got {len(create_task_calls)}"
                    )

        asyncio.run(_run())

    def test_send_reply_uses_asyncio_run_outside_async_context(self):
        """
        When called from a synchronous context (no running loop), _send_reply
        must fall back to asyncio.run — not drop the coroutine silently.
        """
        run_calls = []

        async def _mock_send_whatsapp(msg):
            run_calls.append(msg)

        with patch(
            "notifications.openclaw_notifier.send_whatsapp_message",
            side_effect=_mock_send_whatsapp,
        ):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                with patch(
                    "asyncio.run",
                    side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
                ) as mock_run:
                    from routers.openclaw_router import _send_reply

                    _send_reply("test message sync")

                    # asyncio.run must be called (not the bare coroutine)
                    mock_run.assert_called_once()

    def test_send_reply_never_drops_coroutine_silently(self):
        """
        The coroutine must never be created without a scheduling mechanism.
        This catches the original bug: `send_whatsapp_message(message)` with no
        `await` or `create_task` — the coroutine object is created but never run.
        """
        # If the import fails (no openclaw notifier installed), the function
        # catches the ImportError silently — that's fine; the regression we're
        # guarding is the "import succeeds but coroutine is dropped" path.
        try:
            from routers import openclaw_router  # noqa: F401
        except ImportError:
            pytest.skip("openclaw_router not importable in this environment")

        import inspect

        import routers.openclaw_router as _mod

        src = inspect.getsource(_mod._send_reply)
        # The fix: must NOT have bare `send_whatsapp_message(` without create_task/run
        assert "create_task" in src or "asyncio.run" in src, (
            "_send_reply source no longer contains create_task or asyncio.run — "
            "likely regressed to bare coroutine call"
        )


# ---------------------------------------------------------------------------
# Fix 2: rolling_wfe_scheduler.send_alert wraps notifier.send in asyncio.run
# ---------------------------------------------------------------------------


class TestRollingWfeSchedulerNotifierSend:
    """Verify send_alert wraps notifier.send with asyncio.run (not bare call)."""

    def test_notifier_send_is_driven_via_asyncio_run(self, tmp_path):
        """
        send_alert must call asyncio.run(notifier.send(msg)), not bare notifier.send(msg).
        Verify by checking the source has asyncio.run wrapping.
        """
        import inspect

        from backtest import rolling_wfe_scheduler as _mod

        src = inspect.getsource(_mod.send_alert)
        assert "asyncio.run" in src, (
            "send_alert source no longer uses asyncio.run — "
            "likely regressed to bare notifier.send(msg) call"
        )
        assert "notifier.send" in src, (
            "send_alert source no longer calls notifier.send — " "function structure changed"
        )

    def test_notifier_send_actually_executes_on_halt_verdict(self, tmp_path):
        """
        When verdict is HALT, asyncio.run(notifier.send) must actually be called,
        not silently dropped as an unawaited coroutine.

        asyncio is imported locally inside send_alert, so we patch the
        WhatsAppNotifier and track that asyncio.run receives a coroutine.
        """
        asyncio_run_calls = []

        def mock_asyncio_run(coro):
            asyncio_run_calls.append(coro)
            # Drive the coroutine to completion to avoid leaked-coroutine warnings
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        send_mock = AsyncMock(return_value=None)
        mock_notifier_instance = MagicMock()
        mock_notifier_instance.send = send_mock

        mock_notifier_cls = MagicMock(return_value=mock_notifier_instance)

        # Patch both the WhatsAppNotifier class and asyncio.run globally
        with (
            patch("notifications.whatsapp.WhatsAppNotifier", mock_notifier_cls),
            patch("asyncio.run", side_effect=mock_asyncio_run),
        ):
            from backtest.rolling_wfe_scheduler import send_alert

            send_alert(
                symbol="MCL",  # must be in INSTRUMENT_CONFIGS
                wfe=0.25,
                verdict="HALT",
                prev_wfe=0.60,
            )

        # asyncio.run must have been called (not the coroutine dropped)
        assert (
            len(asyncio_run_calls) >= 1
        ), "asyncio.run was never called — notifier.send coroutine was dropped"


# ---------------------------------------------------------------------------
# Fix 3: JarvisLLMClient.provider class-level default exists before __init__
# ---------------------------------------------------------------------------


class TestJarvisLLMClientProviderDefault:
    """Verify JarvisLLMClient has a class-level provider default."""

    def test_provider_exists_as_class_attribute(self):
        """
        JarvisLLMClient must have `provider` as a class-level attribute.
        Before the fix, provider was only set in __init__, causing AttributeError
        for subclasses, mocks, __new__ callers, and pickle paths.
        """
        from llm.client import JarvisLLMClient

        # Class-level attribute must exist (not just instance-level)
        assert hasattr(JarvisLLMClient, "provider"), (
            "JarvisLLMClient.provider class attribute missing — "
            "AttributeError expected for pre-__init__ access paths"
        )

    def test_provider_class_default_is_string(self):
        """The class-level default must be a string (not None or unset)."""
        from llm.client import JarvisLLMClient

        class_provider = JarvisLLMClient.__dict__.get("provider")
        assert isinstance(
            class_provider, str
        ), f"JarvisLLMClient.provider class default must be a str, got: {type(class_provider)}"

    def test_provider_accessible_before_init_via_new(self):
        """
        A subclass or caller using __new__ must be able to read .provider
        without calling __init__ first — no AttributeError.
        """
        from llm.client import JarvisLLMClient

        # Bypass __init__ using __new__
        instance = JarvisLLMClient.__new__(JarvisLLMClient)

        # Must not raise AttributeError
        try:
            _ = instance.provider
        except AttributeError as exc:
            pytest.fail(
                f"Accessing .provider before __init__ raised AttributeError: {exc}. "
                "Class-level default is missing or was removed."
            )

    def test_provider_default_value_is_ollama(self):
        """
        The class-level default must be 'ollama' (the intended safe default
        that avoids cloud API calls when no env var is set).
        """
        from llm.client import JarvisLLMClient

        class_provider = JarvisLLMClient.__dict__.get("provider", None)
        assert (
            class_provider == "ollama"
        ), f"Expected JarvisLLMClient.provider class default='ollama', got: {class_provider!r}"

    def test_provider_mock_subclass_no_attribute_error(self):
        """
        A MagicMock that spec-matches JarvisLLMClient must expose .provider.
        This is the pattern used by other test files and production code that
        mocks the LLM client.
        """
        from llm.client import JarvisLLMClient

        mock_client = MagicMock(spec=JarvisLLMClient)
        # spec'd mocks reflect class attributes — must not raise
        try:
            _ = mock_client.provider
        except AttributeError as exc:
            pytest.fail(f"MagicMock(spec=JarvisLLMClient).provider raised AttributeError: {exc}")
