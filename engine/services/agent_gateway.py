from __future__ import annotations

import asyncio
import json
import logging
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import anyio
import httpx

from db.session_manager import SessionManager

logger = logging.getLogger(__name__)

AgentName = Literal["openclaw", "hermes"]
ChannelName = Literal["telegram", "whatsapp", "api"]

_STATE_SQL = """
CREATE TABLE IF NOT EXISTS gateway_state (
  channel TEXT NOT NULL,
  user_id TEXT NOT NULL,
  active_agent TEXT NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(channel, user_id)
);
"""


@dataclass(slots=True)
class InboundMessage:
    channel: ChannelName
    user_id: str
    text: str
    reply_target: str
    display_name: str = ""


@dataclass(slots=True)
class AdapterResponse:
    agent: AgentName
    backend: str
    model: str
    session_id: str
    reply_text: str
    latency_ms: int
    health_state: str
    fallback_used: bool = False
    error: Optional[str] = None


@dataclass(slots=True)
class AdapterHealth:
    backend: str
    model: str
    state: str
    detail: str = ""


@dataclass(slots=True)
class GatewayConfig:
    default_agent: AgentName = "openclaw"
    max_history_messages: int = 10
    allowed_telegram_chat_ids: tuple[str, ...] = ()
    allowed_whatsapp_numbers: tuple[str, ...] = ()


@dataclass(slots=True)
class CliBackendConfig:
    backend: str
    model: str
    command_template: str
    status_command: Optional[str] = None
    send_timeout_seconds: float = 240.0
    status_timeout_seconds: float = 20.0


@dataclass(slots=True)
class OllamaBackendConfig:
    backend: str
    model: str
    base_url: str
    timeout_seconds: float = 60.0
    num_ctx: int = 4096
    max_history_messages: int = 4


@dataclass(slots=True)
class OpenAICompatBackendConfig:
    backend: str
    model: str
    base_url: str
    api_key: str = ""


class GatewaySessionStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._session_manager = SessionManager(self.db_path)
        self._ensure_state_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_state_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_STATE_SQL)
            conn.commit()

    def _session_name(self, channel: str, user_id: str, agent: AgentName) -> str:
        return f"messaging:{channel}:{user_id}:{agent}"

    def _find_session_id(self, session_name: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE name = ? ORDER BY id DESC LIMIT 1",
                (session_name,),
            ).fetchone()
            return int(row["id"]) if row else None

    def _find_thread_id(self, session_id: int, agent: AgentName) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM threads WHERE session_id = ? AND agent_name = ? ORDER BY id DESC LIMIT 1",
                (session_id, agent),
            ).fetchone()
            return int(row["id"]) if row else None

    def _get_or_create_thread(self, channel: str, user_id: str, agent: AgentName) -> tuple[int, int]:
        session_name = self._session_name(channel, user_id, agent)
        session_id = self._find_session_id(session_name)
        if session_id is None:
            session_id = self._session_manager.create_session(
                session_name,
                metadata={"channel": channel, "user_id": user_id, "agent": agent},
            )
        thread_id = self._find_thread_id(session_id, agent)
        if thread_id is None:
            thread_id = self._session_manager.create_thread(session_id, agent)
        return session_id, thread_id

    def get_active_agent(self, channel: str, user_id: str, default_agent: AgentName) -> AgentName:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active_agent FROM gateway_state WHERE channel = ? AND user_id = ?",
                (channel, user_id),
            ).fetchone()
            return row["active_agent"] if row else default_agent

    def set_active_agent(self, channel: str, user_id: str, agent: AgentName) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_state(channel, user_id, active_agent, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel, user_id)
                DO UPDATE SET active_agent = excluded.active_agent, updated_at = excluded.updated_at
                """,
                (channel, user_id, agent, now),
            )
            conn.commit()

    def append_user_message(self, channel: str, user_id: str, agent: AgentName, text: str) -> str:
        session_id, thread_id = self._get_or_create_thread(channel, user_id, agent)
        self._session_manager.append_message(thread_id, "user", text, agent_visible=True, user_visible=True)
        return f"{session_id}:{thread_id}"

    def append_assistant_message(self, channel: str, user_id: str, agent: AgentName, text: str) -> str:
        session_id, thread_id = self._get_or_create_thread(channel, user_id, agent)
        self._session_manager.append_message(thread_id, "assistant", text, agent_visible=True, user_visible=True)
        return f"{session_id}:{thread_id}"

    def get_history(self, channel: str, user_id: str, agent: AgentName, limit: int = 10) -> list[dict]:
        _, thread_id = self._get_or_create_thread(channel, user_id, agent)
        messages = self._session_manager.get_thread_messages(thread_id, visibility="agent")
        return [{"role": msg["role"], "content": msg["content"]} for msg in messages[-limit:]]

    def reset_session(self, channel: str, user_id: str, agent: AgentName) -> str:
        session_name = self._session_name(channel, user_id, agent)
        session_id = self._session_manager.create_session(
            session_name,
            metadata={"channel": channel, "user_id": user_id, "agent": agent, "reset": True},
        )
        thread_id = self._session_manager.create_thread(session_id, agent)
        return f"{session_id}:{thread_id}"


class BaseAgentAdapter:
    agent_name: AgentName

    async def send(self, history: list[dict], message: str, session_id: str) -> AdapterResponse:
        raise NotImplementedError

    async def health(self) -> AdapterHealth:
        raise NotImplementedError


class CliAgentAdapter(BaseAgentAdapter):
    def __init__(self, agent_name: AgentName, config: CliBackendConfig):
        self.agent_name = agent_name
        self.config = config

    def _run(self, command: str, timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    async def send(self, history: list[dict], message: str, session_id: str) -> AdapterResponse:
        del history
        start = time.perf_counter()
        command = self.config.command_template.format(message=shlex.quote(message))
        try:
            result = await anyio.to_thread.run_sync(
                self._run, command, self.config.send_timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return AdapterResponse(
                agent=self.agent_name,
                backend=self.config.backend,
                model=self.config.model,
                session_id=session_id,
                reply_text=f"{self.agent_name} backend timed out after {self.config.send_timeout_seconds:.0f}s",
                latency_ms=latency_ms,
                health_state="error",
                error=f"timeout:{exc}",
            )
        latency_ms = int((time.perf_counter() - start) * 1000)
        if result.returncode != 0:
            return AdapterResponse(
                agent=self.agent_name,
                backend=self.config.backend,
                model=self.config.model,
                session_id=session_id,
                reply_text=f"{self.agent_name} backend failed: {result.stderr.strip() or result.stdout.strip()}",
                latency_ms=latency_ms,
                health_state="error",
                error=result.stderr.strip() or result.stdout.strip(),
            )

        # OpenClaw writes its --json payload to stderr, not stdout.
        combined = (result.stdout + "\n" + result.stderr).strip()
        reply_text = _extract_cli_reply(combined)
        return AdapterResponse(
            agent=self.agent_name,
            backend=self.config.backend,
            model=self.config.model,
            session_id=session_id,
            reply_text=reply_text,
            latency_ms=latency_ms,
            health_state="ok",
        )

    async def health(self) -> AdapterHealth:
        if not self.config.status_command:
            return AdapterHealth(self.config.backend, self.config.model, "unknown")
        try:
            result = await anyio.to_thread.run_sync(
                self._run, self.config.status_command, self.config.status_timeout_seconds
            )
        except Exception as exc:
            return AdapterHealth(self.config.backend, self.config.model, "error", str(exc))
        state = "ok" if result.returncode == 0 else "error"
        detail = (result.stdout or result.stderr).strip().splitlines()
        return AdapterHealth(self.config.backend, self.config.model, state, detail[-1] if detail else "")


class OllamaAgentAdapter(BaseAgentAdapter):
    def __init__(
        self,
        agent_name: AgentName,
        primary: OllamaBackendConfig,
        fallback: Optional[OpenAICompatBackendConfig] = None,
    ):
        self.agent_name = agent_name
        self.primary = primary
        self.fallback = fallback

    async def list_models(self) -> list[dict]:
        """Query Ollama for available models."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.primary.base_url.rstrip('/')}/api/tags")
                resp.raise_for_status()
                return resp.json().get("models", [])
        except Exception:
            return []

    def set_model(self, model_name: str) -> None:
        """Change the active model for this adapter."""
        self.primary = OllamaBackendConfig(
            backend=self.primary.backend,
            model=model_name,
            base_url=self.primary.base_url,
        )

    async def _send_ollama(
        self,
        history: list[dict],
        message: str,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
        num_ctx: int | None = None,
    ) -> tuple[str, int]:
        payload = {
            "model": model or self.primary.model,
            "messages": history + [{"role": "user", "content": message}],
            "stream": False,
            "options": {
                "num_ctx": num_ctx or self.primary.num_ctx,
                "num_predict": 384,
            },
        }
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout_seconds or self.primary.timeout_seconds) as client:
            response = await client.post(f"{self.primary.base_url.rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = (data.get("message") or {}).get("content") or ""
        return content.strip(), latency_ms

    async def _send_openai(self, history: list[dict], message: str) -> tuple[str, int]:
        if self.fallback is None:
            raise RuntimeError("openai fallback not configured")
        payload = {
            "model": self.fallback.model,
            "messages": history + [{"role": "user", "content": message}],
            "stream": False,
        }
        headers = {}
        if self.fallback.api_key:
            headers["Authorization"] = f"Bearer {self.fallback.api_key}"
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self.fallback.base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        latency_ms = int((time.perf_counter() - start) * 1000)
        content = data["choices"][0]["message"]["content"]
        return str(content).strip(), latency_ms

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
        try:
            reply_text, latency_ms = await self._send_ollama(
                history[-self.primary.max_history_messages :],
                message,
                model=model,
                timeout_seconds=timeout_seconds,
                num_ctx=num_ctx,
            )
            return AdapterResponse(
                agent=self.agent_name,
                backend=backend,
                model=model,
                session_id=session_id,
                reply_text=reply_text,
                latency_ms=latency_ms,
                health_state="ok",
            )
        except Exception as exc:
            return AdapterResponse(
                agent=self.agent_name,
                backend=backend,
                model=model,
                session_id=session_id,
                reply_text=f"{self.agent_name} {backend} backend unavailable: {exc}",
                latency_ms=0,
                health_state="error",
                error=str(exc),
            )

    async def send(self, history: list[dict], message: str, session_id: str) -> AdapterResponse:
        try:
            reply_text, latency_ms = await self._send_ollama(
                history[-self.primary.max_history_messages :],
                message,
            )
            return AdapterResponse(
                agent=self.agent_name,
                backend=self.primary.backend,
                model=self.primary.model,
                session_id=session_id,
                reply_text=reply_text,
                latency_ms=latency_ms,
                health_state="ok",
            )
        except Exception as primary_exc:
            if self.fallback is None:
                return AdapterResponse(
                    agent=self.agent_name,
                    backend=self.primary.backend,
                    model=self.primary.model,
                    session_id=session_id,
                    reply_text=f"{self.agent_name} local backend unavailable: {primary_exc}",
                    latency_ms=0,
                    health_state="error",
                    error=str(primary_exc),
                )
            try:
                reply_text, latency_ms = await self._send_openai(history, message)
                return AdapterResponse(
                    agent=self.agent_name,
                    backend=self.fallback.backend,
                    model=self.fallback.model,
                    session_id=session_id,
                    reply_text=reply_text,
                    latency_ms=latency_ms,
                    health_state="ok",
                    fallback_used=True,
                )
            except Exception as fallback_exc:
                return AdapterResponse(
                    agent=self.agent_name,
                    backend=self.primary.backend,
                    model=self.primary.model,
                    session_id=session_id,
                    reply_text=(
                        f"{self.agent_name} is unavailable. "
                        f"local={primary_exc} | fallback={fallback_exc}"
                    ),
                    latency_ms=0,
                    health_state="error",
                    error=f"local={primary_exc}; fallback={fallback_exc}",
                )

    async def health(self) -> AdapterHealth:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.primary.base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
            return AdapterHealth(self.primary.backend, self.primary.model, "ok")
        except Exception as exc:
            detail = str(exc)
            if self.fallback is not None:
                return AdapterHealth(self.primary.backend, self.primary.model, "degraded", detail)
            return AdapterHealth(self.primary.backend, self.primary.model, "error", detail)


class SharedAgentGateway:
    def __init__(
        self,
        store: GatewaySessionStore,
        config: GatewayConfig,
        adapters: dict[AgentName, BaseAgentAdapter],
    ):
        self.store = store
        self.config = config
        self.adapters = adapters

    def _is_allowed(self, inbound: InboundMessage) -> bool:
        if inbound.channel == "telegram" and self.config.allowed_telegram_chat_ids:
            return inbound.user_id in self.config.allowed_telegram_chat_ids
        if inbound.channel == "whatsapp" and self.config.allowed_whatsapp_numbers:
            return inbound.user_id in self.config.allowed_whatsapp_numbers
        return True

    async def handle(self, inbound: InboundMessage) -> AdapterResponse:
        if not self._is_allowed(inbound):
            return AdapterResponse(
                agent=self.config.default_agent,
                backend="gateway",
                model="n/a",
                session_id="unauthorized",
                reply_text="Sender not authorized for this messaging gateway.",
                latency_ms=0,
                health_state="unauthorized",
                error="sender_not_allowed",
            )

        text = inbound.text.strip()
        if not text:
            return AdapterResponse(
                agent=self.config.default_agent,
                backend="gateway",
                model="n/a",
                session_id="empty",
                reply_text=(
                    "Send a message or use /status, /fast, /deep, /code, "
                    "/model, /openclaw, /hermes, /both, /agent, or /reset."
                ),
                latency_ms=0,
                health_state="ok",
            )

        return await self._dispatch(inbound, text)

    async def _dispatch(self, inbound: InboundMessage, text: str) -> AdapterResponse:
        lower = text.lower()
        active_agent = self.store.get_active_agent(inbound.channel, inbound.user_id, self.config.default_agent)

        if lower.startswith("/status"):
            return await self._status_response(inbound, active_agent)
        if lower.startswith("/model"):
            return await self._model_response(inbound, active_agent, text)
        if lower.startswith("/fast"):
            return await self._dispatch_profile(
                inbound,
                active_agent,
                text[len("/fast") :].strip(),
                profile="fast",
                model="llama3.2:3b",
                timeout_seconds=45.0,
                num_ctx=4096,
            )
        if lower.startswith("/deep"):
            return await self._dispatch_profile(
                inbound,
                active_agent,
                text[len("/deep") :].strip(),
                profile="deep",
                model="qwen2.5:7b",
                timeout_seconds=180.0,
                num_ctx=8192,
            )
        if lower.startswith("/code"):
            return await self._dispatch_profile(
                inbound,
                active_agent,
                text[len("/code") :].strip(),
                profile="code",
                model="qwen2.5-coder:7b",
                timeout_seconds=180.0,
                num_ctx=8192,
            )
        if lower.startswith("/reset"):
            session_id = self.store.reset_session(inbound.channel, inbound.user_id, active_agent)
            return AdapterResponse(
                agent=active_agent,
                backend="gateway",
                model="n/a",
                session_id=session_id,
                reply_text=f"{active_agent} session reset. Next message starts a fresh thread.",
                latency_ms=0,
                health_state="ok",
            )
        if lower.startswith("/agent "):
            _, _, raw_target = text.partition(" ")
            target = _normalize_agent_name(raw_target.strip())
            self.store.set_active_agent(inbound.channel, inbound.user_id, target)
            return AdapterResponse(
                agent=target,
                backend="gateway",
                model="n/a",
                session_id=f"{inbound.channel}:{inbound.user_id}:{target}",
                reply_text=f"Active agent set to {target}. Future messages will route there.",
                latency_ms=0,
                health_state="ok",
            )

        if lower.startswith("/both"):
            message_text = text[len("/both"):].strip()
            return await self._dispatch_both(inbound, message_text)

        target_agent = active_agent
        message_text = text
        if lower.startswith("/openclaw"):
            target_agent = "openclaw"
            message_text = text[len("/openclaw"):].strip()
            self.store.set_active_agent(inbound.channel, inbound.user_id, target_agent)
        elif lower.startswith("/hermes"):
            target_agent = "hermes"
            message_text = text[len("/hermes"):].strip()
            self.store.set_active_agent(inbound.channel, inbound.user_id, target_agent)

        if not message_text:
            return AdapterResponse(
                agent=target_agent,
                backend="gateway",
                model="n/a",
                session_id=f"{inbound.channel}:{inbound.user_id}:{target_agent}",
                reply_text=f"Send a prompt after /{target_agent} or switch with /agent {target_agent}.",
                latency_ms=0,
                health_state="ok",
            )

        session_id = self.store.append_user_message(inbound.channel, inbound.user_id, target_agent, message_text)
        history = self.store.get_history(
            inbound.channel,
            inbound.user_id,
            target_agent,
            limit=self.config.max_history_messages,
        )
        reply = await self.adapters[target_agent].send(history[:-1], message_text, session_id)
        self.store.append_assistant_message(inbound.channel, inbound.user_id, target_agent, reply.reply_text)
        return reply

    async def _dispatch_profile(
        self,
        inbound: InboundMessage,
        active_agent: AgentName,
        message_text: str,
        *,
        profile: str,
        model: str,
        timeout_seconds: float,
        num_ctx: int,
    ) -> AdapterResponse:
        if not message_text:
            return AdapterResponse(
                agent=active_agent,
                backend="gateway",
                model="n/a",
                session_id=f"{inbound.channel}:{inbound.user_id}:{active_agent}",
                reply_text=f"Send a prompt after /{profile}.",
                latency_ms=0,
                health_state="ok",
            )

        session_id = self.store.append_user_message(
            inbound.channel, inbound.user_id, active_agent, message_text
        )
        history = self.store.get_history(
            inbound.channel,
            inbound.user_id,
            active_agent,
            limit=min(self.config.max_history_messages, 4),
        )
        adapter = self.adapters[active_agent]
        if hasattr(adapter, "send_with_model"):
            reply = await adapter.send_with_model(  # type: ignore[attr-defined]
                history[:-1],
                message_text,
                session_id,
                model=model,
                backend=f"ollama-{profile}",
                timeout_seconds=timeout_seconds,
                num_ctx=num_ctx,
            )
        else:
            reply = await adapter.send(history[:-1], message_text, session_id)
        self.store.append_assistant_message(
            inbound.channel, inbound.user_id, active_agent, reply.reply_text
        )
        return reply

    async def _dispatch_both(self, inbound: InboundMessage, message_text: str) -> AdapterResponse:
        """Fan out one prompt to BOTH adapters in parallel, merge replies.

        Contract: preserves the single-AdapterResponse return type so the
        Telegram/WhatsApp reply paths don't need a new code path. The merged
        reply_text carries both agents' output under **OpenClaw:** / **Hermes:**
        headers. Per-agent session threads each receive the user message and
        their own assistant reply so subsequent targeted prompts still have
        coherent history."""
        if not message_text:
            return AdapterResponse(
                agent=self.config.default_agent,
                backend="gateway",
                model="n/a",
                session_id=f"{inbound.channel}:{inbound.user_id}:both",
                reply_text="Send a prompt after /both — e.g. /both What's the MCL regime?",
                latency_ms=0,
                health_state="ok",
            )

        agents: tuple[AgentName, AgentName] = ("openclaw", "hermes")
        session_ids: dict[AgentName, str] = {}
        histories: dict[AgentName, list] = {}
        for agent in agents:
            session_ids[agent] = self.store.append_user_message(
                inbound.channel, inbound.user_id, agent, message_text
            )
            histories[agent] = self.store.get_history(
                inbound.channel,
                inbound.user_id,
                agent,
                limit=self.config.max_history_messages,
            )

        async def _call(agent: AgentName):
            return await self.adapters[agent].send(
                histories[agent][:-1], message_text, session_ids[agent]
            )

        start = time.monotonic()
        results = await asyncio.gather(
            *(_call(a) for a in agents), return_exceptions=True
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        sections: list[str] = []
        any_error = False
        for agent, result in zip(agents, results, strict=False):
            header = f"**{agent.capitalize()}:**"
            if isinstance(result, BaseException):
                any_error = True
                sections.append(f"{header} ERROR — {type(result).__name__}: {result}")
                continue
            sections.append(f"{header} {result.reply_text}")
            self.store.append_assistant_message(
                inbound.channel, inbound.user_id, agent, result.reply_text
            )

        return AdapterResponse(
            agent=self.config.default_agent,
            backend="gateway-both",
            model="n/a",
            session_id=f"{inbound.channel}:{inbound.user_id}:both",
            reply_text="\n\n".join(sections),
            latency_ms=elapsed_ms,
            health_state="degraded" if any_error else "ok",
        )

    async def _status_response(self, inbound: InboundMessage, active_agent: AgentName) -> AdapterResponse:
        openclaw_health = await self.adapters["openclaw"].health()
        hermes_health = await self.adapters["hermes"].health()
        reply_text = (
            f"channel={inbound.channel}\n"
            f"active_agent={active_agent}\n"
            f"openclaw={openclaw_health.state} [{openclaw_health.backend} | {openclaw_health.model}]\n"
            f"hermes={hermes_health.state} [{hermes_health.backend} | {hermes_health.model}]"
        )
        return AdapterResponse(
            agent=active_agent,
            backend="gateway",
            model="n/a",
            session_id=f"{inbound.channel}:{inbound.user_id}:{active_agent}",
            reply_text=reply_text,
            latency_ms=0,
            health_state="ok",
        )

    async def _model_response(self, inbound: InboundMessage, active_agent: AgentName, full_text: str) -> AdapterResponse:
        adapter = self.adapters[active_agent]
        parts = full_text.split(None, 2)  # /model [subcommand] [arg]
        subcommand = parts[1].lower() if len(parts) > 1 else ""

        if subcommand == "list" and hasattr(adapter, "list_models"):
            models = await adapter.list_models()
            if not models:
                reply_text = "Could not fetch models from Ollama."
            else:
                lines = []
                for m in models:
                    name = m.get("name", "?")
                    size_gb = m.get("size", 0) / 1e9
                    current = " ← active" if name == adapter.primary.model else ""
                    lines.append(f"  {name} ({size_gb:.1f}GB){current}")
                reply_text = f"Available models for {active_agent}:\n" + "\n".join(lines)
        elif subcommand == "set" and len(parts) > 2 and hasattr(adapter, "set_model"):
            new_model = parts[2].strip()
            # Validate model exists
            models = await adapter.list_models()
            model_names = [m.get("name", "") for m in models]
            if new_model not in model_names:
                reply_text = f"Model '{new_model}' not found. Use /model list to see available models."
            else:
                adapter.set_model(new_model)
                reply_text = f"{active_agent} model changed to {new_model}"
        else:
            health = await adapter.health()
            reply_text = (
                f"agent={active_agent}\n"
                f"backend={health.backend}\n"
                f"model={health.model}\n"
                f"state={health.state}\n"
                f"\nCommands: /fast <prompt> | /deep <prompt> | /code <prompt> | "
                f"/model list | /model set <name>"
            )

        return AdapterResponse(
            agent=active_agent,
            backend="gateway",
            model=getattr(adapter, "primary", None) and adapter.primary.model or "n/a",
            session_id=f"{inbound.channel}:{inbound.user_id}:{active_agent}",
            reply_text=reply_text,
            latency_ms=0,
            health_state="ok",
        )


def _normalize_agent_name(value: str) -> AgentName:
    candidate = value.strip().lower()
    if candidate not in ("openclaw", "hermes"):
        raise ValueError(f"Unsupported agent: {value}")
    return candidate  # type: ignore[return-value]



def _find_all_chars_reverse(text: str, char: str) -> list[int]:
    """Return all indices of *char* in *text*, sorted descending (rightmost first)."""
    return sorted((i for i, c in enumerate(text) if c == char), reverse=True)


def _extract_cli_reply(stdout: str) -> str:
    text = stdout.strip()
    if not text:
        return "No response returned."

    # Try parsing JSON objects from stderr+stdout.  OpenClaw writes
    # warnings before the --json payload and may add trailing lines,
    # so json.loads() on substrings fails.  raw_decode handles this.
    decoder = json.JSONDecoder()
    for start_pos in _find_all_chars_reverse(text, "{"):
        try:
            parsed, _ = decoder.raw_decode(text, start_pos)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        extracted = _walk_structured_reply(parsed)
        if extracted:
            return extracted

    # Fallback: scan lines from the bottom for a single-line JSON object.
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        extracted = _walk_structured_reply(parsed)
        if extracted:
            return extracted

    return text.splitlines()[-1].strip()


def _walk_structured_reply(parsed: object) -> str:
    """Pull a human-readable reply out of varied CLI JSON shapes.

    Known shapes:
      - OpenClaw: {"result": {"payloads": [{"text": "..."}]}}
      - Ollama chat wrappers: {"message": {"content": "..."}}
      - Flat: {"text"|"response"|"message"|"content"|"output": "..."}
      - List of message dicts: [..., {"content": "..."}]
    """

    if isinstance(parsed, dict):
        # OpenClaw payloads
        result = parsed.get("result")
        if isinstance(result, dict):
            payloads = result.get("payloads")
            if isinstance(payloads, list):
                chunks = [
                    item.get("text")
                    for item in payloads
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
                joined = "\n".join(c for c in chunks if c and c.strip()).strip()
                if joined:
                    return joined

        # Ollama-style chat wrapper
        message = parsed.get("message")
        if isinstance(message, dict):
            value = message.get("content")
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("text", "response", "message", "content", "output"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(parsed, list) and parsed:
        tail = parsed[-1]
        if isinstance(tail, dict):
            value = tail.get("content") or tail.get("text")
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""
