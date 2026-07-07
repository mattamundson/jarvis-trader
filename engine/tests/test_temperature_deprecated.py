"""Regression: `temperature` param must be dropped for claude-opus-4-7.

Background (2026-04-21 20:35 CT): pm2 logs showed repeated BadRequestError on
advisor_trader and advisor_debate calls: "'temperature' is deprecated for this
model." Anthropic deprecated the sampling temperature parameter for
claude-opus-4-7; passing it returns a 400.

The fix at engine/llm/client.py drops the `temperature` kwarg from
messages.create(...) when the model matches a prefix in
_TEMPERATURE_DEPRECATED_PREFIXES. All other models continue to receive
temperature unchanged.

This test locks the model-gating predicate against regressions. If Anthropic
later deprecates temperature for more models, extend the prefix tuple and add
the new model IDs to the positive set below.
"""

from llm.client import _temperature_deprecated


class TestTemperatureDeprecated:
    """Which models should have temperature dropped from the Anthropic call?"""

    def test_opus_4_7_exact_match(self):
        assert _temperature_deprecated("claude-opus-4-7") is True

    def test_opus_4_7_with_1m_suffix(self):
        assert _temperature_deprecated("claude-opus-4-7[1m]") is True

    def test_sonnet_4_6_unchanged(self):
        assert _temperature_deprecated("claude-sonnet-4-6") is False

    def test_haiku_4_5_unchanged(self):
        assert _temperature_deprecated("claude-haiku-4-5-20251001") is False

    def test_opus_4_6_unchanged(self):
        assert _temperature_deprecated("claude-opus-4-6") is False

    def test_empty_string(self):
        assert _temperature_deprecated("") is False

    def test_none_safe(self):
        assert _temperature_deprecated(None) is False

    def test_unknown_model_unchanged(self):
        assert _temperature_deprecated("claude-fictional-9-9") is False


class TestLowLevelCallDropsTemperature:
    """End-to-end guard: _call_with_retry must omit the `temperature` kwarg
    when the model is claude-opus-4-7. Mocks the underlying Anthropic client
    and asserts the kwargs that would hit the wire.

    This is the integration gap the prefix-only tests above leave open: a
    future refactor could change how LLMClient routes models without
    touching _temperature_deprecated, and the prefix tests would still pass
    while the advisor started hitting 400s again.
    """

    def _make_client_with_mock(self, monkeypatch):
        import asyncio

        from llm.client import JarvisLLMClient

        client = JarvisLLMClient.__new__(JarvisLLMClient)
        captured: dict = {}

        class FakeMessages:
            async def create(self, **kwargs):
                captured["kwargs"] = kwargs

                class _Usage:
                    input_tokens = 10
                    output_tokens = 5

                class _Resp:
                    usage = _Usage()
                    content = [type("B", (), {"text": "ok"})()]
                    stop_reason = "end_turn"

                return _Resp()

        class FakeAnthropic:
            messages = FakeMessages()

        client.client = FakeAnthropic()
        client.provider = "anthropic"  # override class default so _call_with_retry skips Ollama
        return client, captured, asyncio

    def test_opus_4_7_drops_temperature_at_wire(self, monkeypatch):
        client, captured, asyncio = self._make_client_with_mock(monkeypatch)
        asyncio.run(
            client._call_with_retry(
                model="claude-opus-4-7",
                system="s",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=16,
                temperature=0.2,
            )
        )
        assert "temperature" not in captured["kwargs"], (
            "temperature must be dropped for claude-opus-4-7 or the "
            "advisor path will 400 on every call"
        )
        assert captured["kwargs"]["model"] == "claude-opus-4-7"

    def test_sonnet_retains_temperature_at_wire(self, monkeypatch):
        client, captured, asyncio = self._make_client_with_mock(monkeypatch)
        asyncio.run(
            client._call_with_retry(
                model="claude-sonnet-4-6",
                system="s",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=16,
                temperature=0.2,
            )
        )
        assert captured["kwargs"].get("temperature") == 0.2

    def test_opus_4_7_1m_suffix_drops_temperature(self, monkeypatch):
        """Matches advisor's likely runtime model string on 1M context."""
        client, captured, asyncio = self._make_client_with_mock(monkeypatch)
        asyncio.run(
            client._call_with_retry(
                model="claude-opus-4-7[1m]",
                system="s",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=16,
                temperature=0.2,
            )
        )
        assert "temperature" not in captured["kwargs"]
