from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_phase1_integration_boundary.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_phase1_boundary", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_active_paths_do_not_import_draft_domain_authorities():
    module = _load_script()
    report = module.scan_repository(Path(__file__).resolve().parents[2])
    assert report["adoption_active"] is False
    assert report["pass"] is True
    assert report["violations"] == []


def test_scanner_detects_direct_domain_import(tmp_path: Path):
    module = _load_script()
    path = tmp_path / "active.py"
    path.write_text("from domain.oms import OmsState\n", encoding="utf-8")
    violations = module.scan_file(path)
    assert violations == [{"path": str(path), "line": 1, "module": "domain.oms"}]


def test_scanner_detects_engine_domain_import(tmp_path: Path):
    module = _load_script()
    path = tmp_path / "active.py"
    path.write_text("import engine.domain.risk_policy\n", encoding="utf-8")
    violations = module.scan_file(path)
    assert violations == [
        {"path": str(path), "line": 1, "module": "engine.domain.risk_policy"}
    ]


def test_unrelated_imports_are_allowed(tmp_path: Path):
    module = _load_script()
    path = tmp_path / "active.py"
    path.write_text("from risk.safety_layer import SafetyLayer\n", encoding="utf-8")
    assert module.scan_file(path) == []
