"""
Global state and dependency injection for JARVIS TRADER

All routers import these globals to access app-wide resources.
main.py initializes these during lifespan, then all routers share them.
"""

from datetime import datetime
from typing import Dict

# Pipeline WhatsApp cooldown state lives in
# ``notifications.pipeline_alert_cooldown`` (single source of truth).

# Market Data Manager
data_manager = None

# Safety & Risk
safety_layer = None
pnl_monitor = None
loss_tracker = None

# Trading Components
technical_analyst = None
trading_pipeline = None
scheduler = None
paper_tracker = None
order_manager = None

# Database & Tracking
db_manager = None
eod_scheduler = None
cost_tracker = None

# WebSocket
ws_manager = None

# Shared utility state
_start_time: datetime = None
_macro_cache: Dict[str, dict] = {}


def inject_all_dependencies(
    dm,
    sl,
    ta,
    tp,
    sched,
    pt,
    dbm,
    pm,
    eod,
    om,
    wsm,
    ct,
    lt,
    st,
):
    """
    Inject all dependencies from main.py lifespan.
    Called once during FastAPI app startup.
    """
    global data_manager, safety_layer, technical_analyst, trading_pipeline
    global scheduler, paper_tracker, db_manager, pnl_monitor
    global eod_scheduler, order_manager, ws_manager, cost_tracker
    global loss_tracker, _start_time
    data_manager = dm
    safety_layer = sl
    technical_analyst = ta
    trading_pipeline = tp
    scheduler = sched
    paper_tracker = pt
    db_manager = dbm
    pnl_monitor = pm
    eod_scheduler = eod
    order_manager = om
    ws_manager = wsm
    cost_tracker = ct
    loss_tracker = lt
    _start_time = st
