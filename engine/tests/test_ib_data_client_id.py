"""Offline tests for the data-leg IB clientId separation + bounded connect retry.

The data connector must NOT reuse the executor's IBKR_CLIENT_ID (IB Gateway
rejects a duplicate clientId), and a transient non-timeout connect failure must
be retried while a real timeout (gateway not listening) fails fast.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from data.market_data import IBKRDataConnector, resolve_data_client_id


class _Cfg:
    def __init__(self, client_id=1, data_client_id=None):
        self.IBKR_CLIENT_ID = client_id
        if data_client_id is not None:
            self.IBKR_DATA_CLIENT_ID = data_client_id


# --- resolve_data_client_id ------------------------------------------------

def test_data_client_id_offsets_executor_by_default():
    assert resolve_data_client_id(_Cfg(client_id=1)) == 2
    assert resolve_data_client_id(_Cfg(client_id=243)) == 244


def test_data_client_id_honors_explicit_override():
    assert resolve_data_client_id(_Cfg(client_id=1, data_client_id=50)) == 50


def test_data_client_id_zero_explicit_falls_back_to_offset():
    assert resolve_data_client_id(_Cfg(client_id=7, data_client_id=0)) == 8


def test_data_client_id_never_equals_executor():
    for cid in (1, 5, 243):
        assert resolve_data_client_id(_Cfg(client_id=cid)) != cid


# --- connect() retry behavior ----------------------------------------------

def _mock_ib_factory(connect_side_effects):
    """Build an IB() factory whose connectAsync pops the next side effect:
    None -> success, Exception instance -> raise. Records each instance."""
    instances = []
    seq = list(connect_side_effects)

    def factory(*_a, **_k):
        ib = MagicMock()
        ib.disconnect = MagicMock()

        async def _connect(*_ca, **_ck):
            eff = seq.pop(0)
            if isinstance(eff, BaseException):
                raise eff
            return eff

        ib.connectAsync = _connect
        instances.append(ib)
        return ib

    return factory, instances


@pytest.mark.asyncio
async def test_connect_succeeds_first_attempt():
    conn = IBKRDataConnector(client_id=9)
    factory, instances = _mock_ib_factory([None])
    with patch("ib_async.IB", side_effect=factory):
        ok = await conn.connect(retries=2, retry_backoff=0)
    assert ok is True and conn._connected is True
    assert len(instances) == 1


@pytest.mark.asyncio
async def test_connect_retries_nontimeout_then_succeeds():
    conn = IBKRDataConnector(client_id=9)
    factory, instances = _mock_ib_factory([ConnectionError("clientId in use"), None])
    with patch("ib_async.IB", side_effect=factory):
        ok = await conn.connect(retries=2, retry_backoff=0)
    assert ok is True and conn._connected is True
    assert len(instances) == 2                  # retried once
    instances[0].disconnect.assert_called()     # half-open socket dropped first


@pytest.mark.asyncio
async def test_connect_gives_up_after_exhausting_retries():
    conn = IBKRDataConnector(client_id=9)
    effects = [ConnectionError("x"), ConnectionError("x"), ConnectionError("x")]
    factory, instances = _mock_ib_factory(effects)
    with patch("ib_async.IB", side_effect=factory):
        ok = await conn.connect(retries=2, retry_backoff=0)
    assert ok is False and conn._connected is False
    assert len(instances) == 3                  # 1 + 2 retries


@pytest.mark.asyncio
async def test_connect_timeout_fails_fast_without_retry():
    conn = IBKRDataConnector(client_id=9)
    factory, instances = _mock_ib_factory([asyncio.TimeoutError(), None])
    with patch("ib_async.IB", side_effect=factory):
        ok = await conn.connect(retries=2, retry_backoff=0)
    assert ok is False and conn._connected is False
    assert len(instances) == 1                  # NO retry on a timeout
