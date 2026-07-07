"""Unit tests — gate-v2 integrity guard (Initiative 2A).

Exercises the static checker in engine/scripts/check_gate_v2_integrity.py with
synthetic fixture dirs (deterministic, git-free) plus a live smoke over the
real engine/backtest tree.

Run with the engine venv (pytest OR standalone — worktree pytest collection is
broken by a pre-existing conftest db dependency, so __main__ runs it directly):
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_gate_v2_integrity.py -q
    engine/.venv/Scripts/python.exe engine/tests/test_gate_v2_integrity.py
"""

import pathlib
import sys
import tempfile

_ENGINE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ENGINE / "scripts"))

import check_gate_v2_integrity as g  # noqa: E402

# --- minimal source fixtures --------------------------------------------------
_TRADE_RUNNER = '''"""Fake canonical runner.
Writes: engine/data/gate_v2_verdicts/{verdict}.json
"""
def _compute_gate_v2(oos_results, n_grid_combos):
    from backtest._gate_v2_trade_metrics import trade_level_dsr, trade_level_mc_95th_dd
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=CAPITAL)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    return mc_95th_dd, dsr
'''

_WINDOW_RUNNER = '''"""Fake dead runner.
Writes: engine/data/gate_v2_verdicts/{verdict}.json
"""
def _compute_gate_v2(oos_dds, mean_sharpe, n_grid_combos, n_obs):
    from backtest.deflated_sharpe import deflated_sharpe_ratio
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    dsr_result = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_grid_combos, n_obs=n_obs)
    return mc_95th_dd, dsr_result
'''


def _paper_config(symbol: str, verdict: str | None, enabled: bool = True) -> str:
    verdict_line = (
        f"    #  Verdict file: engine/data/gate_v2_verdicts/{verdict}.json (created 2026-05-06)\n"
        if verdict
        else ""
    )
    return (
        f"FOO_CONFIG = {{\n"
        f"{verdict_line}"
        f'    "symbol": "{symbol}",\n'
        f'    "enabled": {enabled},\n'
        f'    "multiplier": 5.0,\n'
        f"}}\n"
    )


def _mkdir_fixture(paper_config_src: str, runners: dict[str, str]) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix="gv2itest_"))
    (d / "paper_config.py").write_text(paper_config_src, encoding="utf-8")
    for name, src in runners.items():
        (d / name).write_text(src, encoding="utf-8")
    return d


# --- classification -----------------------------------------------------------
def test_classify_trade_level():
    info = g.RunnerInfo(pathlib.Path("run_x.py"), _TRADE_RUNNER.format(verdict="MES_trend_rank11"))
    assert info.has_compute_gate is True
    assert info.has_trade_calls is True
    assert info.is_trade_level is True  # window pattern co-exists but trade calls win
    assert info.has_window_pattern is True
    assert "MES_trend_rank11" in info.writes


def test_classify_window_level():
    info = g.RunnerInfo(pathlib.Path("run_y.py"), _WINDOW_RUNNER.format(verdict="MES_donchian_rank1"))
    assert info.has_compute_gate is True
    assert info.has_trade_calls is False
    assert info.is_trade_level is False
    assert info.has_window_pattern is True


# --- paper_config parsing -----------------------------------------------------
def test_parse_paper_config_enabled_with_verdict():
    enabled = g.parse_paper_config(_paper_config("MES", "MES_trend_rank11"))
    assert enabled == {"MES": "MES_trend_rank11"}


def test_parse_paper_config_disabled_excluded():
    enabled = g.parse_paper_config(_paper_config("MES", "MES_trend_rank11", enabled=False))
    assert enabled == {}


def test_parse_paper_config_enabled_missing_verdict():
    enabled = g.parse_paper_config(_paper_config("MES", None))
    assert enabled == {"MES": None}


# --- audit (T1 + WARN) --------------------------------------------------------
def test_audit_green_when_canonical_trade_level():
    d = _mkdir_fixture(
        _paper_config("MES", "MES_trend_rank11"),
        {
            "run_mes_trend_rank11.py": _TRADE_RUNNER.format(verdict="MES_trend_rank11"),
            "run_mes_donchian_rank1.py": _WINDOW_RUNNER.format(verdict="MES_donchian_rank1"),
        },
    )
    failures, warnings = g.audit(d)
    assert failures == []
    # the dead window-level runner writing an MES verdict is a WARN, not a fail
    assert any("run_mes_donchian_rank1.py" in w for w in warnings)


def test_audit_fails_when_canonical_window_level():
    d = _mkdir_fixture(
        _paper_config("MES", "MES_trend_rank11"),
        {"run_mes_trend_rank11.py": _WINDOW_RUNNER.format(verdict="MES_trend_rank11")},
    )
    failures, _ = g.audit(d)
    assert any("T1 MES" in f and "does not call trade_level" in f for f in failures)


def test_audit_fails_when_verdict_comment_missing():
    d = _mkdir_fixture(
        _paper_config("MES", None),
        {"run_mes_trend_rank11.py": _TRADE_RUNNER.format(verdict="MES_trend_rank11")},
    )
    failures, _ = g.audit(d)
    assert any("T1 MES" in f and "undocumented" in f for f in failures)


def test_audit_fails_when_no_producing_runner():
    d = _mkdir_fixture(_paper_config("MES", "MES_trend_rank11"), {})
    failures, _ = g.audit(d)
    assert any("T1 MES" in f and "not produced by any" in f for f in failures)


# --- T2 new-file gate ---------------------------------------------------------
def test_check_new_files_skips_when_newness_unknown():
    # repo_root=None → newness can't be determined → must NOT block.
    d = _mkdir_fixture(_paper_config("MES", "MES_trend_rank11"), {})
    p = d / "run_new_window.py"
    p.write_text(_WINDOW_RUNNER.format(verdict="ZZZ_new_rank1"), encoding="utf-8")
    assert g.check_new_files([p], repo_root=None) == []


def test_check_new_files_flags_new_window_runner(monkeypatch):
    d = _mkdir_fixture(_paper_config("MES", "MES_trend_rank11"), {})
    p = d / "run_new_window.py"
    p.write_text(_WINDOW_RUNNER.format(verdict="ZZZ_new_rank1"), encoding="utf-8")
    monkeypatch.setattr(g, "_is_new_file", lambda path, root: True)
    failures = g.check_new_files([p], repo_root=d)
    assert any("T2 run_new_window.py" in f for f in failures)


def test_check_new_files_allows_new_trade_runner(monkeypatch):
    d = _mkdir_fixture(_paper_config("MES", "MES_trend_rank11"), {})
    p = d / "run_new_trade.py"
    p.write_text(_TRADE_RUNNER.format(verdict="ZZZ_new_rank1"), encoding="utf-8")
    monkeypatch.setattr(g, "_is_new_file", lambda path, root: True)
    assert g.check_new_files([p], repo_root=d) == []


def test_check_new_files_exempts_existing_window_runner(monkeypatch):
    # An EXISTING (not new) dead runner being edited must not be blocked.
    d = _mkdir_fixture(_paper_config("MES", "MES_trend_rank11"), {})
    p = d / "run_old_window.py"
    p.write_text(_WINDOW_RUNNER.format(verdict="OLD_rank1"), encoding="utf-8")
    monkeypatch.setattr(g, "_is_new_file", lambda path, root: False)
    assert g.check_new_files([p], repo_root=d) == []


# --- live smoke over the real tree --------------------------------------------
def test_live_audit_real_backtest_has_no_t1_failures():
    backtest = _ENGINE / "backtest"
    if not backtest.exists():
        return  # not in a full checkout
    failures, _warnings = g.audit(backtest)
    assert failures == [], f"real-tree T1 violations: {failures}"


if __name__ == "__main__":
    import traceback

    # monkeypatch shim so standalone mode can run the monkeypatch-using tests
    class _MP:
        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)

        def undo(self):
            for obj, name, old in reversed(self._undo):
                setattr(obj, name, old)
            self._undo.clear()

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        mp = _MP()
        try:
            if fn.__code__.co_argcount == 1:
                fn(mp)
            else:
                fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
        finally:
            mp.undo()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
