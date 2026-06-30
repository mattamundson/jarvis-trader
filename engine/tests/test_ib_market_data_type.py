"""
JARVIS TRADER — IB delayed-data stopgap tests
=============================================
Covers the reqMarketDataType call added to IBKRDataConnector.connect().

Context: the 2026-06-29 frozen-MES-5300 contamination traced to the IB paper
account having no futures market-data subscription (Error 10168/354). The engine
never requested DELAYED data, so the data leg errored and fell through to a
months-old CSV cache. reqMarketDataType(3) requests delayed data when no live
subscription exists (IB still returns live where subscribed). Default 3, override
via IB_MARKET_DATA_TYPE. The call is non-fatal — a failure must not abort connect.
"""

from __future__ import annotations

import pytest

from data.market_data import IBKRDataConnector


class _FakeEvent:
    """Minimal stand-in for an ib_async Event supporting +=."""

    def __iadd__(self, _handler):
        return self


class _FakeIB:
    """Records reqMarketDataType calls; connectAsync is an async no-op."""

    def __init__(self):
        self.market_data_type_calls: list[int] = []
        self.disconnectedEvent = _FakeEvent()

    async def connectAsync(self, host, port, clientId=None):  # noqa: N803 (IB API name)
        return None

    def reqMarketDataType(self, n):  # noqa: N802 (IB API name)
        self.market_data_type_calls.append(n)

    def disconnect(self):
        pass


@pytest.fixture
def _patch_ib(monkeypatch):
    """Point `from ib_async import IB` (inside connect) at _FakeIB."""
    import ib_async

    monkeypatch.setattr(ib_async, "IB", _FakeIB)
    return _FakeIB


class TestReqMarketDataTypeStopgap:
    @pytest.mark.asyncio
    async def test_defaults_to_delayed_3(self, monkeypatch, _patch_ib):
        monkeypatch.delenv("IB_MARKET_DATA_TYPE", raising=False)
        conn = IBKRDataConnector(port=4002, client_id=99)
        ok = await conn.connect(retries=0)
        assert ok is True
        assert conn._ib.market_data_type_calls == [3]

    @pytest.mark.asyncio
    async def test_env_override_honored(self, monkeypatch, _patch_ib):
        monkeypatch.setenv("IB_MARKET_DATA_TYPE", "1")
        conn = IBKRDataConnector(port=4002, client_id=99)
        await conn.connect(retries=0)
        assert conn._ib.market_data_type_calls == [1]

    @pytest.mark.asyncio
    async def test_invalid_env_value_skips_call(self, monkeypatch, _patch_ib):
        """Out-of-range / garbage values do not call reqMarketDataType, but the
        connection still succeeds (the stopgap must never break connect)."""
        monkeypatch.setenv("IB_MARKET_DATA_TYPE", "9")
        conn = IBKRDataConnector(port=4002, client_id=99)
        ok = await conn.connect(retries=0)
        assert ok is True
        assert conn._ib.market_data_type_calls == []

    @pytest.mark.asyncio
    async def test_reqtype_failure_is_non_fatal(self, monkeypatch):
        """If reqMarketDataType raises, connect() still returns True."""

        class _RaisingIB(_FakeIB):
            def reqMarketDataType(self, n):  # noqa: N802
                raise RuntimeError("boom")

        import ib_async

        monkeypatch.setattr(ib_async, "IB", _RaisingIB)
        monkeypatch.delenv("IB_MARKET_DATA_TYPE", raising=False)
        conn = IBKRDataConnector(port=4002, client_id=99)
        ok = await conn.connect(retries=0)
        assert ok is True
