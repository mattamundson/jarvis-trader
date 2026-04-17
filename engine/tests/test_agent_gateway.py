from __future__ import annotations

from dataclasses import dataclass

from services.agent_gateway import (
    AdapterHealth,
    AdapterResponse,
    GatewayConfig,
    GatewaySessionStore,
    InboundMessage,
    SharedAgentGateway,
)


@dataclass
class StubAdapter:
    agent_name: str

    async def send(self, history: list[dict], message: str, session_id: str) -> AdapterResponse:
        return AdapterResponse(
            agent=self.agent_name,
            backend=f"{self.agent_name}-backend",
            model=f"{self.agent_name}-model",
            session_id=session_id,
            reply_text=f"{self.agent_name}:{message}:{len(history)}",
            latency_ms=1,
            health_state="ok",
        )

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            backend=f"{self.agent_name}-backend",
            model=f"{self.agent_name}-model",
            state="ok",
        )


def build_gateway(tmp_path, **config_overrides) -> tuple[SharedAgentGateway, GatewaySessionStore]:
    db_path = tmp_path / "gateway.db"
    store = GatewaySessionStore(db_path)
    config = GatewayConfig(**config_overrides)
    gateway = SharedAgentGateway(
        store=store,
        config=config,
        adapters={
            "openclaw": StubAdapter("openclaw"),
            "hermes": StubAdapter("hermes"),
        },
    )
    return gateway, store


async def test_agent_command_sets_default_route(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path)

    reply = await gateway.handle(
        InboundMessage(channel="telegram", user_id="u1", text="/agent hermes", reply_target="u1")
    )
    assert reply.reply_text == "Active agent set to hermes. Future messages will route there."

    follow_up = await gateway.handle(
        InboundMessage(channel="telegram", user_id="u1", text="What is running?", reply_target="u1")
    )
    assert follow_up.agent == "hermes"
    assert follow_up.reply_text.startswith("hermes:What is running?")


async def test_explicit_prefix_overrides_active_agent(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path)

    await gateway.handle(
        InboundMessage(channel="telegram", user_id="u1", text="/agent hermes", reply_target="u1")
    )
    reply = await gateway.handle(
        InboundMessage(channel="telegram", user_id="u1", text="/openclaw check status", reply_target="u1")
    )

    assert reply.agent == "openclaw"
    assert reply.reply_text.startswith("openclaw:check status")


async def test_allowlist_blocks_unauthorized_sender(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path, allowed_telegram_chat_ids=("approved",))

    reply = await gateway.handle(
        InboundMessage(channel="telegram", user_id="not-approved", text="/status", reply_target="x")
    )

    assert reply.health_state == "unauthorized"
    assert reply.error == "sender_not_allowed"


async def test_sessions_are_isolated_per_agent(tmp_path) -> None:
    gateway, store = build_gateway(tmp_path)

    await gateway.handle(
        InboundMessage(channel="whatsapp", user_id="15551234567", text="/openclaw first", reply_target="15551234567")
    )
    await gateway.handle(
        InboundMessage(channel="whatsapp", user_id="15551234567", text="/hermes second", reply_target="15551234567")
    )

    openclaw_history = store.get_history("whatsapp", "15551234567", "openclaw")
    hermes_history = store.get_history("whatsapp", "15551234567", "hermes")

    assert [msg["content"] for msg in openclaw_history] == ["first", "openclaw:first:0"]
    assert [msg["content"] for msg in hermes_history] == ["second", "hermes:second:0"]


async def test_reset_starts_new_session(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path)

    first = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="hello", reply_target="u1")
    )
    reset = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/reset", reply_target="u1")
    )
    second = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="hello again", reply_target="u1")
    )

    assert first.session_id != reset.session_id
    assert second.session_id == reset.session_id
