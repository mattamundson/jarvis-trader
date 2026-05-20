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


@dataclass
class ProfileStubAdapter(StubAdapter):
    async def send_with_model(
        self,
        history: list[dict],
        message: str,
        session_id: str,
        *,
        model: str,
        backend: str,
        timeout_seconds: float,
        num_ctx: int,
    ) -> AdapterResponse:
        return AdapterResponse(
            agent=self.agent_name,
            backend=backend,
            model=model,
            session_id=session_id,
            reply_text=f"{backend}:{model}:{num_ctx}:{int(timeout_seconds)}:{message}:{len(history)}",
            latency_ms=1,
            health_state="ok",
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


def build_profile_gateway(tmp_path, **config_overrides) -> tuple[SharedAgentGateway, GatewaySessionStore]:
    db_path = tmp_path / "gateway.db"
    store = GatewaySessionStore(db_path)
    config = GatewayConfig(**config_overrides)
    gateway = SharedAgentGateway(
        store=store,
        config=config,
        adapters={
            "openclaw": ProfileStubAdapter("openclaw"),
            "hermes": ProfileStubAdapter("hermes"),
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


@dataclass
class RaisingAdapter:
    agent_name: str
    exc: Exception

    async def send(self, history: list[dict], message: str, session_id: str) -> AdapterResponse:
        raise self.exc

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            backend=f"{self.agent_name}-backend",
            model=f"{self.agent_name}-model",
            state="error",
        )


async def test_both_command_dispatches_to_each_adapter(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path)

    reply = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/both What is 2+2?", reply_target="u1")
    )

    assert reply.backend == "gateway-both"
    assert reply.health_state == "ok"
    assert "**Openclaw:** openclaw:What is 2+2?" in reply.reply_text
    assert "**Hermes:** hermes:What is 2+2?" in reply.reply_text


async def test_both_command_appends_to_both_agent_threads(tmp_path) -> None:
    gateway, store = build_gateway(tmp_path)

    await gateway.handle(
        InboundMessage(channel="telegram", user_id="u42", text="/both same prompt", reply_target="u42")
    )

    openclaw_history = store.get_history("telegram", "u42", "openclaw")
    hermes_history = store.get_history("telegram", "u42", "hermes")

    assert [msg["content"] for msg in openclaw_history] == ["same prompt", "openclaw:same prompt:0"]
    assert [msg["content"] for msg in hermes_history] == ["same prompt", "hermes:same prompt:0"]


async def test_both_command_tolerates_one_adapter_failure(tmp_path) -> None:
    db_path = tmp_path / "gateway.db"
    store = GatewaySessionStore(db_path)
    config = GatewayConfig()
    gateway = SharedAgentGateway(
        store=store,
        config=config,
        adapters={
            "openclaw": StubAdapter("openclaw"),
            "hermes": RaisingAdapter("hermes", RuntimeError("ollama down")),
        },
    )

    reply = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/both check", reply_target="u1")
    )

    assert reply.health_state == "degraded"
    assert "**Openclaw:** openclaw:check" in reply.reply_text
    assert "**Hermes:** ERROR — RuntimeError: ollama down" in reply.reply_text

    # Successful agent's reply is persisted; failed agent's thread only has the user message
    openclaw_history = store.get_history("api", "u1", "openclaw")
    hermes_history = store.get_history("api", "u1", "hermes")
    assert [m["content"] for m in openclaw_history] == ["check", "openclaw:check:0"]
    assert [m["content"] for m in hermes_history] == ["check"]


async def test_both_command_with_empty_prompt_returns_help(tmp_path) -> None:
    gateway, _ = build_gateway(tmp_path)

    reply = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/both", reply_target="u1")
    )

    assert reply.backend == "gateway"
    assert "Send a prompt after /both" in reply.reply_text


async def test_fast_command_uses_small_model_profile(tmp_path) -> None:
    gateway, _ = build_profile_gateway(tmp_path)

    reply = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/fast ping", reply_target="u1")
    )

    assert reply.backend == "ollama-fast"
    assert reply.model == "llama3.2:3b"
    assert reply.reply_text.startswith("ollama-fast:llama3.2:3b:4096:45:ping")


async def test_deep_and_code_commands_use_explicit_heavy_profiles(tmp_path) -> None:
    gateway, _ = build_profile_gateway(tmp_path)

    deep = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/deep analyze this", reply_target="u1")
    )
    code = await gateway.handle(
        InboundMessage(channel="api", user_id="u1", text="/code fix this", reply_target="u1")
    )

    assert deep.backend == "ollama-deep"
    assert deep.model == "qwen2.5:7b"
    assert ":8192:180:analyze this" in deep.reply_text
    assert code.backend == "ollama-code"
    assert code.model == "qwen2.5-coder:7b"
    assert ":8192:180:fix this" in code.reply_text
