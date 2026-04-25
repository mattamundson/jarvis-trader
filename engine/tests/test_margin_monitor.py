from risk.margin_monitor import MarginMonitorAgent


class _SummaryConnector:
    async def get_account_summary(self):
        return {
            "equity": 10000.0,
            "buying_power": 40000.0,
            "margin_used": 1200.0,
        }


class _BalanceConnector:
    async def get_account_balance(self):
        return {
            "equity": 9000.0,
            "buying_power": 30000.0,
            "margin_used": 900.0,
        }


class _NoAccountConnector:
    pass


async def test_margin_monitor_uses_account_summary_when_available():
    agent = MarginMonitorAgent(connector=_SummaryConnector())

    result = await agent.check_health()

    assert result["status"] == "HEALTHY"
    assert result["metrics"]["equity"] == 10000.0


async def test_margin_monitor_falls_back_to_account_balance():
    agent = MarginMonitorAgent(connector=_BalanceConnector())

    result = await agent.check_health()

    assert result["status"] == "HEALTHY"
    assert result["metrics"]["equity"] == 9000.0


async def test_margin_monitor_skips_when_connector_has_no_account_methods():
    agent = MarginMonitorAgent(connector=_NoAccountConnector())

    result = await agent.check_health()

    assert result["status"] == "SKIPPED"
    assert "does not expose account health metrics" in result["message"]
