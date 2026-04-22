import pytest

from approval.service import ApprovalFlowError, approve_pending_trade


@pytest.mark.asyncio
async def test_approve_pending_trade_requires_safety_layer(tmp_path):
    from database.manager import DatabaseManager
    from portfolio.tracker import PortfolioTracker

    db_path = tmp_path / "approval.db"
    trades_path = tmp_path / "paper_trades.jsonl"

    db = DatabaseManager(str(db_path))
    db.initialize()
    tracker = PortfolioTracker(store_path=trades_path, db_manager=db)

    approval_id = db.insert_pending_approval(
        symbol="MCL",
        action="buy",
        quantity=1.0,
        entry_price=72.5,
        pipeline_snapshot={"summary": "approval regression"},
        timeframe="1h",
    )

    with pytest.raises(ApprovalFlowError) as exc_info:
        await approve_pending_trade(
            approval_id=approval_id,
            db_manager=db,
            paper_tracker=tracker,
            safety_layer=None,
            resolved_by="test",
        )

    assert exc_info.value.status_code == 503
    assert db.get_pending_approval(approval_id)["status"] == "pending"
    assert tracker.get_open_positions() == []
