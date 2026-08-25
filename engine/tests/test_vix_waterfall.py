"""Unit tests for the VIX waterfall in data.market_data (get_vix).

Verifies the freshest-first ordering introduced on 2026-08-24:
    IBKR live → FRED EOD → Yahoo intraday → Polygon → unavailable

Covers the three behaviors that matter:
  1. IBKR is tried first and wins when it has a price (the reorder).
  2. The FRED tier uses the real method name (get_latest, not the
     non-existent get_latest_value) and returns FRED when IBKR is down.
  3. Yahoo intraday is a no-cost fallback, and the whole chain degrades
     to {"value": None, "source": "unavailable"} without raising.
"""

import asyncio

import pytest


class _FakeIBKR:
    """Minimal fake for the .ibkr attribute of the market-data facade."""

    def __init__(self, connected: bool = True, last_price: float | None = 21.5):
        self.is_connected = connected
        self._last_price = last_price

    async def get_snapshot_price(self, symbol: str, is_futures: bool = False) -> dict:
        if self._last_price is None:
            return {"last_price": None, "source": "ibkr_no_price"}
        return {"last_price": self._last_price, "source": "ibkr"}


class _FakePolygon:
    def __init__(self, value: float | None = None):
        self._value = value

    def get_vix_value(self) -> dict:
        if self._value is None:
            return {"value": None, "source": "polygon_unavailable"}
        return {"value": self._value, "source": "polygon"}


@pytest.fixture
def facade_factory(monkeypatch):
    """Build a MarketDataFacade-like object with the waterfall fakeable.

    Rather than instantiating the full facade (which pulls in heavy
    dependencies), we construct a lightweight stand-in exposing the same
    attributes get_vix reads: .ibkr, .polygon, ._config.
    """
    import types

    def _make(ibkr=None, polygon=None):
        class _Config:
            FRED_API_KEY = None

        obj = types.SimpleNamespace(
            ibkr=ibkr,
            polygon=polygon,
            _config=_Config(),
        )
        return obj

    return _make


def _install_waterfall(monkeypatch, facade):
    """Attach the real get_vix (unbound) to the fake facade."""
    from data import market_data as md

    monkeypatch.setattr(
        facade,
        "get_vix",
        md.MarketDataManager.get_vix.__get__(facade, type(facade)),
        raising=False,
    )
    return facade


def test_get_vix_prefers_ibkr_when_live(facade_factory, monkeypatch):
    """IBKR is the first tier; when it has a price, it wins."""
    fake_ibkr = _FakeIBKR(connected=True, last_price=14.75)
    facade = facade_factory(ibkr=fake_ibkr, polygon=None)

    _install_waterfall(monkeypatch, facade)

    result = asyncio.run(facade.get_vix())

    assert result["source"] == "ibkr"
    assert result["value"] == 14.75
    assert "ts" in result


def test_get_vix_falls_back_to_fred_when_ibkr_down(facade_factory, monkeypatch):
    """When IBKR has no price, the FRED tier (direct fredgraph CSV) is used."""
    fake_ibkr = _FakeIBKR(connected=False)
    facade = facade_factory(ibkr=fake_ibkr, polygon=None)

    _install_waterfall(monkeypatch, facade)

    # Stub urlopen inside the data module to return a VIXCLS CSV body.
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"observation_date,VIXCLS\n2026-08-20,17.30\n2026-08-21,17.31\n"

    def _fake_urlopen(url, timeout=30):
        assert "VIXCLS" in url
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    result = asyncio.run(facade.get_vix())

    assert result["source"] == "fred"
    assert result["value"] == 17.31
    assert result["ts"] == "2026-08-21"


def test_get_vix_yahoo_fallback_when_ibkr_and_fred_unavailable(facade_factory, monkeypatch):
    """Yahoo intraday is tried when both IBKR and FRED fail."""
    fake_ibkr = _FakeIBKR(connected=False)
    facade = facade_factory(ibkr=fake_ibkr, polygon=None)

    _install_waterfall(monkeypatch, facade)

    # FRED fails (network down -> exception inside the tier).
    def _fred_boom(url, timeout=30):
        raise OSError("fred down for test")

    monkeypatch.setattr("urllib.request.urlopen", _fred_boom)

    # Fake yfinance to return a tiny intraday frame.
    import pandas as pd

    class _FakeHist:
        empty = False

        def __init__(self, df):
            self._df = df

        def __getitem__(self, key):
            if key == "Close":
                return self._df["Close"]
            raise KeyError(key)

        @property
        def index(self):
            return self._df.index

        @property
        def shape(self):
            return self._df.shape

    class _FakeTicker:
        def __init__(self, sym):
            pass

        def history(self, **kwargs):
            idx = pd.to_datetime(["2026-08-24 09:31:00-05:00"])
            df = pd.DataFrame({"Close": [15.4]}, index=idx)
            return _FakeHist(df)

    monkeypatch.setattr("yfinance.Ticker", _FakeTicker)

    result = asyncio.run(facade.get_vix())

    assert result["source"] == "yahoo"
    assert result["value"] == 15.4
    assert "ts" in result


def test_get_vix_polygon_last_and_full_degradation(facade_factory, monkeypatch):
    """Polygon is last resort; when everything fails, return unavailable."""
    fake_ibkr = _FakeIBKR(connected=False)
    fake_poly = _FakePolygon(value=19.9)
    facade = facade_factory(ibkr=fake_ibkr, polygon=fake_poly)

    _install_waterfall(monkeypatch, facade)

    # FRED fails too.
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout=30: (_ for _ in ()).throw(OSError("fred down")),
    )

    # Force yfinance to fail so the chain falls through to Polygon.
    def _boom(*args, **kwargs):
        raise RuntimeError("network down for test")

    monkeypatch.setattr("yfinance.Ticker", _boom)

    result = asyncio.run(facade.get_vix())

    assert result["source"] == "polygon"
    assert result["value"] == 19.9

    # Now everything fails
    fake_ibkr2 = _FakeIBKR(connected=False)
    fake_poly2 = _FakePolygon(value=None)
    facade2 = facade_factory(ibkr=fake_ibkr2, polygon=fake_poly2)

    _install_waterfall(monkeypatch, facade2)

    result2 = asyncio.run(facade2.get_vix())
    assert result2["value"] is None
    assert result2["source"] == "unavailable"
