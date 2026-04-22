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
