"""
Unit tests for the three dashboard routes added to stop the panels 404ing:
  GET /options/module/scan, GET /options/module/pnl, GET /portfolio/capital

Handlers are called directly with monkeypatched lazy dependencies. They must
follow the graceful-degradation contract: never raise, return a typed-empty
payload when the backing service is absent.
"""

import pytest

import orchestrator
import routers.options_router as orr
import routers.portfolio_router as pr

# ── /portfolio/capital ───────────────────────────────────────────────────────


class _Mod:
    def __init__(self, capital, target):
        self.capital_allocated = capital
        self.daily_target = target


class _Health:
    def __init__(self, market, status):
        self.market = market
        self.status = status  # plain str -> code takes the str(h.status) branch


class _Orch:
    def __init__(self):
        self.daily_target = 500.0
        self._m = {"futures": _Mod(10000.0, 300.0), "options": _Mod(5000.0, 200.0)}

    def list_modules(self):
        return list(self._m)

    def get_module(self, name):
        return self._m.get(name)

    def get_all_health(self):
        return [_Health("futures", "ok"), _Health("options", "disabled")]


@pytest.mark.asyncio
async def test_portfolio_capital_no_orchestrator(monkeypatch):
    monkeypatch.setattr(pr, "_get_orchestrator", lambda: None)
    out = await pr.portfolio_capital()
    assert out["markets"] == {}
    assert out["enabled_markets"] == []
    assert out["total_capital"] > 0  # falls back to settings.INITIAL_CAPITAL


@pytest.mark.asyncio
async def test_portfolio_capital_with_orchestrator(monkeypatch):
    monkeypatch.setattr(pr, "_get_orchestrator", lambda: _Orch())
    out = await pr.portfolio_capital()
    assert out["markets"]["futures"] == {"capital": 10000.0, "daily_target": 300.0}
    assert out["total_capital"] == 15000.0
    assert out["daily_target"] == 500.0
    assert out["enabled_markets"] == ["futures"]  # 'options' disabled -> filtered


# ── /options/module/scan ─────────────────────────────────────────────────────


class _OptHealth:
    daily_pnl = 42.0
    vix_regime = "high"
    current_strategy = "iron_condor"


class _OptModule:
    def health_check(self):
        return _OptHealth()


class _OrchOpt:
    def __init__(self, module):
        self._module = module

    def get_module(self, name):
        return self._module if name == "options" else None


@pytest.mark.asyncio
async def test_options_scan_no_orchestrator(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: None)
    out = await orr.options_module_scan()
    assert out["scan_results"] == []
    assert out["vix_regime"] == "normal"


@pytest.mark.asyncio
async def test_options_scan_reads_module_metadata(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: _OrchOpt(_OptModule()))
    out = await orr.options_module_scan()
    assert out["vix_regime"] == "high"
    assert out["strategy_selected"] == "iron_condor"
    assert out["scan_results"] == []  # module exposes no last_scan_results


# ── /options/module/pnl ──────────────────────────────────────────────────────


class _Pos:
    def __init__(self, symbol, entry, current, pnl, dte):
        self.symbol = symbol
        self.strategy = "iron_condor"
        self.entry_premium = entry
        self.current_premium = current
        self._pnl = pnl
        self._dte = dte

    @property
    def unrealised_pnl(self):
        return self._pnl

    @property
    def dte(self):
        return self._dte


@pytest.mark.asyncio
async def test_options_pnl_maps_positions(monkeypatch):
    import options.position_manager as pmmod

    class _Mgr:
        def get_positions(self, status="OPEN"):
            return [_Pos("SPY", 1.0, 0.5, 50.0, 20)]

    monkeypatch.setattr(pmmod, "OptionsPositionManager", _Mgr)
    monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: None)  # daily_pnl -> total

    out = await orr.options_module_pnl()
    assert len(out["open_positions"]) == 1
    p = out["open_positions"][0]
    assert p["symbol"] == "SPY"
    assert p["entry_price"] == 1.0
    assert p["current_price"] == 0.5
    assert p["pnl"] == 50.0
    assert p["dte"] == 20
    assert out["total_pnl"] == 50.0
    assert out["daily_pnl"] == 50.0  # orchestrator absent -> mirrors summed unrealised


@pytest.mark.asyncio
async def test_options_pnl_empty_on_manager_failure(monkeypatch):
    import options.position_manager as pmmod

    class _BoomMgr:
        def __init__(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(pmmod, "OptionsPositionManager", _BoomMgr)
    monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: None)

    out = await orr.options_module_pnl()  # must not raise
    assert out["open_positions"] == []
    assert out["total_pnl"] == 0.0
