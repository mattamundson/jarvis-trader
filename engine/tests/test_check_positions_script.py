from scripts.check_positions import format_positions_response, main


def test_format_positions_response_groups_brokers() -> None:
    payload = {
        "ibkr": {"connected": True, "positions": [{"symbol": "MES", "side": "BUY", "quantity": 2, "avg_cost": 4523.5, "unrealized_pnl": 125.3}]},
        "schwab": {"positions": [{"symbol": "AAPL", "direction": "BUY", "contracts": 100, "entry_price": 175.2, "pnl": 45.6}]},
        "paper": {"positions": []},
    }

    rendered = format_positions_response(payload)

    assert "Positions (IBKR connected):" in rendered
    assert "MES" in rendered
    assert "x2@4523.50" in rendered
    assert "pnl=+125.30" in rendered
    assert "AAPL" in rendered


def test_format_positions_response_empty() -> None:
    rendered = format_positions_response({"ibkr": {"connected": False}, "schwab": {}, "paper": {}})

    assert rendered == "Positions (IBKR DISCONNECTED):\n  No open positions."


def test_main_requires_api_key(capsys, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    assert main(["--engine-url", "http://127.0.0.1:8010"]) == 2
    assert "Missing API key" in capsys.readouterr().err
