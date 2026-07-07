"""Pipeline task board router — exposes live stage tracking."""

from fastapi import APIRouter

from agents.task_board import get_task_board

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/board")
async def get_pipeline_board():
    """Get current pipeline stage execution status."""
    return get_task_board().get_status()


@router.post("/board/reset")
async def reset_pipeline_board():
    """Reset the task board (clears last run state)."""
    get_task_board().reset()
    return {"status": "reset"}
