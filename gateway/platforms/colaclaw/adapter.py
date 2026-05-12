"""
ColaClaw platform adapter: HTTP ingress + callback delivery (Phase 2 events).

Text-first transport; structured v2 callbacks with legacy opt-in.
"""

from __future__ import annotations

import logging
import os
import socket as _socket
from typing import Any, Dict, Optional

try:
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult

from .contract import (
    ASSISTANT_COMPLETED,
    ASSISTANT_ERROR,
    ASSISTANT_PROGRESS,
    COLACLAW_CHAT_TRANSPORT,
    build_v2_callback_payload,
    classify_assistant_event_type,
    is_legacy_callback_schema,
    parse_callback_payload,
)
from .inbound import handle_inbound_request
from .outbound import post_callback

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8650


def check_colaclaw_requirements() -> bool:
    return AIOHTTP_AVAILABLE


def _status_for_event(event_type: str, *, completed: Optional[bool] = None) -> str:
    if event_type == ASSISTANT_PROGRESS:
        return "in_progress"
    if event_type == ASSISTANT_ERROR:
        return "failed"
    if event_type == ASSISTANT_COMPLETED:
        return "completed" if completed else "failed"
    return "ok"


class ColaClawAdapter(BasePlatformAdapter):
    """Receives ColaClaw JSON POSTs and sends replies via HTTP callback."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.COLACLAW)
        extra = config.extra or {}
        self._host: str = str(extra.get("host", os.getenv("COLACLAW_HOST", DEFAULT_HOST)))
        self._port: int = int(extra.get("port", os.getenv("COLACLAW_PORT", str(DEFAULT_PORT))))
        self.shared_secret: str = str(
            extra.get("secret", os.getenv("COLACLAW_SECRET", ""))
        ).strip()
        self._callback_url: str = str(
            extra.get("callback_url", os.getenv("COLACLAW_CALLBACK_URL", ""))
        ).strip()
        self._callback_secret: str = str(
            extra.get(
                "callback_secret",
                os.getenv("COLACLAW_CALLBACK_SECRET", self.shared_secret),
            )
        ).strip()
        self._legacy_schema: bool = is_legacy_callback_schema(extra)
        self._runner: Optional[web.AppRunner] = None
        self._client: Any = None
        self._callback_context: Dict[str, Dict[str, str]] = {}
        self._sequence_by_chat: Dict[str, int] = {}

    def remember_callback_context(
        self,
        chat_id: str,
        *,
        workspace_id: str,
        session_id: str,
        user_id: str,
    ) -> None:
        self._callback_context[chat_id] = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "user_id": user_id,
        }

    def _resolve_ctx(self, chat_id: str) -> Dict[str, str]:
        ctx = self._callback_context.get(chat_id, {})
        workspace_id = ctx.get("workspace_id", "")
        session_id = ctx.get("session_id", "")
        user_id = ctx.get("user_id", "")
        prefix = f"{COLACLAW_CHAT_TRANSPORT}|"
        if chat_id.startswith(prefix):
            segs = chat_id.split("|")
            if len(segs) >= 4:
                workspace_id = workspace_id or segs[1]
                user_id = user_id or segs[2]
                session_id = session_id or segs[3]
        elif not workspace_id or not session_id:
            parts = chat_id.split(":", 1)
            if len(parts) == 2:
                auto_workspace_id, auto_session_id = parts[0], parts[1]
            else:
                auto_workspace_id, auto_session_id = "", chat_id
            workspace_id = workspace_id or auto_workspace_id
            session_id = session_id or auto_session_id
        return {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "user_id": user_id,
        }

    def _next_sequence(self, chat_id: str) -> int:
        n = self._sequence_by_chat.get(chat_id, 0) + 1
        self._sequence_by_chat[chat_id] = n
        return n

    async def emit_turn_completion_marker(self, chat_id: str, *, ok: bool) -> None:
        """ColaClaw Phase 2 — signal end of handler turn (hook from BasePlatformAdapter)."""
        if not self._callback_url:
            return
        if not self._client:
            return
        if self._legacy_schema:
            logger.debug("[colaclaw] Legacy callback schema — skip assistant.completed")
            return

        ctx = self._resolve_ctx(chat_id)
        payload = build_v2_callback_payload(
            workspace_id=ctx["workspace_id"],
            session_id=ctx["session_id"],
            user_id=ctx["user_id"],
            event_type=ASSISTANT_COMPLETED,
            sequence=self._next_sequence(chat_id),
            text="",
            status=_status_for_event(ASSISTANT_COMPLETED, completed=ok),
        )
        ok_cb, err = await post_callback(
            self._client,
            self._callback_url,
            payload,
            secret=self._callback_secret,
        )
        if not ok_cb:
            logger.warning("[colaclaw] assistant.completed callback failed: %s", err)

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "platform": "colaclaw"})

    async def _handle_inbound_message(self, request: web.Request) -> web.Response:
        return await handle_inbound_request(self, request)

    async def connect(self) -> bool:
        if not AIOHTTP_AVAILABLE:
            logger.error("[colaclaw] aiohttp not installed")
            return False

        if not self.shared_secret:
            logger.warning(
                "[colaclaw] COLACLAW_SECRET is empty — requests are not authenticated (local testing only)"
            )

        if not self._callback_url:
            logger.warning(
                "[colaclaw] COLACLAW_CALLBACK_URL is empty — assistant replies cannot be delivered"
            )

        if self._legacy_schema:
            logger.info("[colaclaw] COLACLAW_CALLBACK_SCHEMA=legacy (Phase 1 flat payloads for messages)")

        import aiohttp

        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
                _s.settimeout(1)
                _s.connect(("127.0.0.1", self._port))
            logger.error(
                "[colaclaw] Port %d already in use — set COLACLAW_PORT",
                self._port,
            )
            return False
        except (ConnectionRefusedError, OSError):
            pass

        self._client = aiohttp.ClientSession()

        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_post("/colaclaw/v1/messages", self._handle_inbound_message)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        self._mark_connected()

        logger.info(
            "[colaclaw] Listening on http://%s:%s — POST /colaclaw/v1/messages",
            self._host,
            self._port,
        )
        return True

    async def disconnect(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        if self._client:
            await self._client.close()
            self._client = None
        self._mark_disconnected()
        logger.info("[colaclaw] Disconnected")

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
    ) -> SendResult:
        """
        Tool-progress loop treats ColaClaw like an editable surface.

        Each \"edit\" posts the full accumulated progress text as assistant.progress.
        """
        del message_id
        return await self.send(
            chat_id,
            content,
            metadata={"hermes_outbound_kind": "progress"},
        )

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        del reply_to

        if not self._callback_url:
            logger.error("[colaclaw] No callback URL configured; dropping message")
            return SendResult(success=False, error="COLACLAW_CALLBACK_URL not set")

        if not self._client:
            return SendResult(success=False, error="client session not available")

        event_type = classify_assistant_event_type(metadata)

        if self._legacy_schema:
            if event_type in (ASSISTANT_PROGRESS, ASSISTANT_COMPLETED):
                logger.debug(
                    "[colaclaw] legacy schema — dropping type=%s",
                    event_type,
                )
                return SendResult(success=True, message_id="legacy-drop")
            ctx = self._resolve_ctx(chat_id)
            payload = parse_callback_payload(
                workspace_id=ctx["workspace_id"],
                session_id=ctx["session_id"],
                user_id=ctx["user_id"],
                content=content,
                message_type="message",
            )
        else:
            ctx = self._resolve_ctx(chat_id)
            payload = build_v2_callback_payload(
                workspace_id=ctx["workspace_id"],
                session_id=ctx["session_id"],
                user_id=ctx["user_id"],
                event_type=event_type,
                sequence=self._next_sequence(chat_id),
                text=content,
                status=_status_for_event(
                    event_type,
                    completed=None,
                ),
            )

        ok, err = await post_callback(
            self._client,
            self._callback_url,
            payload,
            secret=self._callback_secret,
        )
        if ok:
            sid = self._resolve_ctx(chat_id)["session_id"]
            return SendResult(success=True, message_id=str(sid))
        return SendResult(success=False, error=err or "callback failed")

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        sid = chat_id.split(":", 1)[-1] if ":" in chat_id else chat_id
        return {"name": f"colaclaw:{sid}", "type": "dm"}
