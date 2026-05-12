"""HTTP ingress for ColaClaw → Hermes (Phase 1)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gateway.platforms.base import MessageEvent, MessageType

from .auth import verify_colaclaw_auth
from .contract import ColaclawInboundMessage, MAX_BODY_BYTES, composite_chat_id

if TYPE_CHECKING:
    from aiohttp import web

    from .adapter import ColaClawAdapter

logger = logging.getLogger(__name__)


async def handle_inbound_request(adapter: "ColaClawAdapter", request: "web.Request") -> "web.Response":
    """Validate POST body, build MessageEvent, queue handle_message, return 202."""
    from aiohttp import web

    auth_resp = verify_colaclaw_auth(request, adapter.shared_secret)
    if auth_resp is not None:
        return auth_resp

    try:
        raw = await request.read()
        if len(raw) > MAX_BODY_BYTES:
            return web.json_response({"error": "payload too large"}, status=413)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return web.json_response({"error": "JSON object required"}, status=400)
        msg = ColaclawInboundMessage.from_payload(data)
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    chat_id = composite_chat_id(msg.workspace_id, msg.user_id, msg.session_id)
    source = adapter.build_source(
        chat_id=chat_id,
        chat_name=f"colaclaw:{msg.session_id}",
        chat_type="dm",
        user_id=msg.user_id,
        user_name=(msg.metadata.get("userName") or msg.metadata.get("user_name")),
    )
    event = MessageEvent(
        text=msg.content,
        message_type=MessageType.TEXT,
        source=source,
        raw_message=data,
        message_id=str(data.get("requestId") or data.get("messageId") or "") or None,
    )

    _json_att_n = len(msg.attachments)
    try:
        from .media_hydration import hydrate_colaclaw_attachments_to_event

        await hydrate_colaclaw_attachments_to_event(event, msg.attachments)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception:
        logger.exception("[colaclaw] attachment hydration failed")
        return web.json_response(
            {"error": "attachment_download_failed"},
            status=502,
        )

    if event.media_urls:
        from gateway.inbound_attachment_context import normalize_message_type_for_media

        normalize_message_type_for_media(event)

    _media_n = len(event.media_urls)
    if _media_n:
        _p0 = event.media_urls[0]
        logger.info(
            "[colaclaw] After hydrate: json_attachments=%d media_paths=%d msg_type=%s "
            "first_cache_basename=%s cache_exists=%s",
            _json_att_n,
            _media_n,
            event.message_type.value,
            Path(_p0).name,
            Path(_p0).is_file(),
        )
    else:
        logger.info(
            "[colaclaw] After hydrate: json_attachments=%d media_paths=0 msg_type=%s",
            _json_att_n,
            event.message_type.value,
        )

    adapter.remember_callback_context(
        chat_id,
        workspace_id=msg.workspace_id,
        session_id=msg.session_id,
        user_id=msg.user_id,
    )

    logger.info(
        "[colaclaw] Inbound workspace=%s session=%s user=%s text_len=%d attachments=%d",
        msg.workspace_id,
        msg.session_id,
        msg.user_id,
        len(msg.content),
        len(msg.attachments),
    )

    asyncio.create_task(adapter.handle_message(event))

    return web.json_response(
        {
            "ok": True,
            "accepted": True,
            "workspaceId": msg.workspace_id,
            "sessionId": msg.session_id,
            "chatId": chat_id,
        },
        status=202,
    )
