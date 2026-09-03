"""Order-path gateway factory (P0-2).

Chooses which gateway object the FastAPI lifespan attaches to the safety layer,
order router, order manager, and position reconciler. Default is the in-process
``IBGatewayConnector`` simulator; when ``IB_PAPER_BROKER_ENABLED`` is set AND
paper mode is on, it returns the real ``IBGatewayManager`` bound to the IB paper
account on port 4002 so orders actually reach the broker.

The returned object is duck-typed compatible at every call site the lifespan
wires (``connect``, ``is_connected``, ``place_paper_order`` with ``parent_order_id``,
``get_positions``, ``get_open_orders``, ``get_order_status``, ``cancel_order``),
so the rest of ``main.py`` is unchanged regardless of which is returned.

Design + proof plan: docs/ROADMAP_P0-2_SCOPE_2026-07-21.md.  [safety-review]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("jarvis_trader.execution.order_gateway_factory")


def build_order_gateway(
    settings: Any,
    safety_layer: Any,
    portfolio_tracker: Any = None,
) -> Any:
    """Return the gateway to attach to the order path.

    Real ``IBGatewayManager`` iff ``IB_PAPER_BROKER_ENABLED`` is truthy AND
    ``PAPER_TRADING`` is on; otherwise the in-process ``IBGatewayConnector``
    simulator. Raises ``ValueError`` when the order-leg clientId would collide
    with the data leg (IB silently evicts the second socket) or when the
    configured port is a live-trading port (``IBGatewayConfig.__post_init__``).
    """
    real_enabled = bool(getattr(settings, "IB_PAPER_BROKER_ENABLED", False))
    paper = bool(getattr(settings, "PAPER_TRADING", True))

    if real_enabled:
        if not paper:
            raise ValueError(
                "IB_PAPER_BROKER_ENABLED requires PAPER_TRADING=True; "
                "refusing to construct a broker-mutating gateway"
            )
        if bool(getattr(settings, "LIVE_TRADING_ENABLED", False)):
            raise ValueError(
                "IB_PAPER_BROKER_ENABLED requires LIVE_TRADING_ENABLED=False"
            )
        if not bool(getattr(settings, "IBKR_PAPER_MODE", False)):
            raise ValueError(
                "IB_PAPER_BROKER_ENABLED requires IBKR_PAPER_MODE=True"
            )

        broker_port = int(getattr(settings, "IBKR_PORT", 0))
        if broker_port != 4002:
            raise ValueError(
                "IB_PAPER_BROKER_ENABLED requires the approved IB Gateway paper port 4002"
            )

        account_id = str(getattr(settings, "IB_ACCOUNT_ID", "") or "").strip()
        if not account_id:
            raise ValueError(
                "IB_PAPER_BROKER_ENABLED requires a non-empty IB_ACCOUNT_ID"
            )

        # Import here so the default (simulator) path never pulls ib_async.
        from data.market_data import resolve_data_client_id
        from execution.ib_gateway import IBGatewayConfig, IBGatewayManager

        order_client_id = int(getattr(settings, "IBKR_CLIENT_ID", 1))
        data_client_id = int(resolve_data_client_id(settings))
        if order_client_id == data_client_id:
            raise ValueError(
                "IB clientId collision: order leg and data leg would both use "
                f"clientId={order_client_id}; IB silently evicts the second socket. "
                "Set a distinct IBKR_DATA_CLIENT_ID or IBKR_CLIENT_ID."
            )

        cfg = IBGatewayConfig(
            host=getattr(settings, "IBKR_HOST", "127.0.0.1"),
            port=broker_port,
            client_id=order_client_id,
            account=account_id,
            timeout=float(getattr(settings, "IBKR_CONNECT_TIMEOUT_SECONDS", 10.0)),
        )
        logger.warning(
            "IB_PAPER_BROKER_ENABLED=1 -> attaching REAL IBGatewayManager "
            "(port=%s order_client_id=%s data_client_id=%s account=%s). "
            "Orders will reach the IB paper account.",
            cfg.port,
            order_client_id,
            data_client_id,
            cfg.account or "<unset>",
        )
        return IBGatewayManager(cfg)

    from execution.ib_gateway_connector import IBGatewayConnector

    return IBGatewayConnector(settings, safety_layer, portfolio_tracker=portfolio_tracker)
