from __future__ import annotations

from importlib import util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "gateway_keeper_reconnect.py"
SPEC = util.spec_from_file_location("gateway_keeper_reconnect", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_read_api_key_strips_quotes_without_printing_secret(tmp_path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=x\nAPI_KEY='secret-value'\n", encoding="utf-8")

    assert MODULE.read_api_key(env_path) == "secret-value"
    assert "secret-value" not in capsys.readouterr().out


def test_authoritative_checks_require_paper_and_both_ib_legs():
    healthy = {
        "ibgateway_alive": True,
        "execution_connected_verified": True,
        "ib_execution_stale": False,
        "ibkr_data_connected": True,
        "live_trading": False,
    }
    assert all(MODULE.authoritative_checks(healthy).values())

    for field, unsafe_value in (
        ("ibgateway_alive", False),
        ("execution_connected_verified", False),
        ("ib_execution_stale", True),
        ("ibkr_data_connected", False),
        ("live_trading", True),
    ):
        payload = dict(healthy)
        payload[field] = unsafe_value
        assert MODULE.authoritative_checks(payload)[field] is False
