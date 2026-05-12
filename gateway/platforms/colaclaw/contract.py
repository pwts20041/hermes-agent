"""
ColaClaw HTTP contract: inbound messages and outbound callback payloads.

Phase 2 adds versioned v2 envelopes; Phase 1 flat shape remains via legacy mode.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Maximum inbound JSON body (Phase 1/2 + Phase 10E attachment metadata)
MAX_BODY_BYTES = 400_000

_MAX_ATTACHMENTS = 8

# Outbound schema version (bump only for breaking consumer-facing changes)
CALLBACK_VERSION = "2026-05-10"

# Implemented event types (Phase 2)
ASSISTANT_MESSAGE = "assistant.message"
ASSISTANT_PROGRESS = "assistant.progress"
ASSISTANT_COMPLETED = "assistant.completed"
ASSISTANT_ERROR = "assistant.error"

# Reserved for documentation / forward compatibility
RESERVED_EVENT_TYPES = frozenset({
    "assistant.stream_delta",
    "tool.started",
    "tool.progress",
    "tool.completed",
    "tool.error",
})

_METADATA_KIND_PROGRESS = "progress"
_METADATA_KIND_STATUS = "status"
_METADATA_KIND_MESSAGE = "message"
_METADATA_KIND_ERROR = "error"


def classify_assistant_event_type(metadata: Optional[Dict[str, Any]]) -> str:
    """
    Map gateway metadata to ColaClaw v2 event type.

    Prefer explicit hermes_outbound_kind; default assistant.message.
    """
    meta = metadata or {}
    kind = meta.get("hermes_outbound_kind")
    if kind == _METADATA_KIND_PROGRESS or kind == _METADATA_KIND_STATUS:
        return ASSISTANT_PROGRESS
    if kind == _METADATA_KIND_ERROR:
        return ASSISTANT_ERROR
    return ASSISTANT_MESSAGE


def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_legacy_callback_schema(extra: Optional[Dict[str, Any]] = None) -> bool:
    """True when ColaClaw should emit Phase 1 flat callbacks only."""
    import os

    ex = extra or {}
    raw = str(
        ex.get("callback_schema", os.getenv("COLACLAW_CALLBACK_SCHEMA", "v2"))
    ).strip().lower()
    return raw in ("legacy", "phase1", "v1")


def build_v2_callback_payload(
    *,
    workspace_id: str,
    session_id: str,
    user_id: str,
    event_type: str,
    sequence: int,
    text: str = "",
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Structured SaaS-facing callback body (Phase 2 default)."""
    eid = event_id or str(uuid.uuid4())
    body: Dict[str, Any] = {
        "version": CALLBACK_VERSION,
        "eventId": eid,
        "workspaceId": workspace_id,
        "userId": user_id,
        "sessionId": session_id,
        "source": "hermes",
        "type": event_type,
        "sequence": sequence,
        "content": {"text": text},
        "status": status,
        "metadata": dict(metadata) if metadata else {},
        "createdAt": utc_now_iso_z(),
    }
    return body


def build_legacy_flat_payload(
    *,
    workspace_id: str,
    session_id: str,
    user_id: str,
    content: str,
    message_type: str = "message",
) -> Dict[str, Any]:
    """Phase 1 compatibility shape (flat content string)."""
    return {
        "workspaceId": workspace_id,
        "sessionId": session_id,
        "userId": user_id,
        "type": message_type,
        "content": content,
    }


# Backwards name for Phase 1 imports
def parse_callback_payload(
    *,
    workspace_id: str,
    session_id: str,
    user_id: str,
    content: str,
    message_type: str = "message",
) -> Dict[str, Any]:
    """Outbound callback body (Phase 1 / legacy)."""
    return build_legacy_flat_payload(
        workspace_id=workspace_id,
        session_id=session_id,
        user_id=user_id,
        content=content,
        message_type=message_type,
    )


@dataclass
class ColaclawAttachmentRef:
    """Phase 10E: signed HTTPS URL Hermes fetches to populate media cache."""

    download_url: str
    mime_type: str
    kind: str  # "image" | "file"
    file_name: Optional[str] = None

    @staticmethod
    def from_item(item: Any) -> "ColaclawAttachmentRef":
        if not isinstance(item, dict):
            raise ValueError("each attachment must be an object")
        url = str(
            item.get("downloadUrl") or item.get("download_url") or ""
        ).strip()
        if not url:
            raise ValueError("attachment.downloadUrl is required")
        if len(url) > 4096:
            raise ValueError("attachment.downloadUrl is too long")
        if not url.startswith(("http://", "https://")):
            raise ValueError("attachment.downloadUrl must be http(s)")
        mime = str(item.get("mimeType") or item.get("mime_type") or "").strip()
        if not mime:
            raise ValueError("attachment.mimeType is required")
        mime = mime.split(";")[0].strip().lower()
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in ("image", "file"):
            raise ValueError("attachment.kind must be image or file")
        raw_name = item.get("fileName") or item.get("file_name")
        file_name: Optional[str] = None
        if raw_name is not None:
            file_name = str(raw_name).strip() or None
        return ColaclawAttachmentRef(
            download_url=url,
            mime_type=mime,
            kind=kind,
            file_name=file_name,
        )


@dataclass
class ColaclawInboundMessage:
    """Normalized inbound message from ColaClaw SaaS."""

    workspace_id: str
    user_id: str
    session_id: str
    type: str = "text"
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[ColaclawAttachmentRef] = field(default_factory=list)

    @staticmethod
    def from_payload(data: Dict[str, Any]) -> "ColaclawInboundMessage":
        if not isinstance(data, dict):
            raise ValueError("Body must be a JSON object")
        ws = str(data.get("workspaceId") or data.get("workspace_id") or "").strip()
        uid = str(data.get("userId") or data.get("user_id") or "").strip()
        sid = str(data.get("sessionId") or data.get("session_id") or "").strip()
        if not ws or not uid or not sid:
            raise ValueError("workspaceId, userId, and sessionId are required")
        if ":" in ws:
            raise ValueError("workspaceId must not contain ':'")
        if ":" in uid:
            raise ValueError("userId must not contain ':'")
        if ":" in sid:
            raise ValueError("sessionId must not contain ':'")
        if "|" in ws:
            raise ValueError("workspaceId must not contain '|'")
        if "|" in uid:
            raise ValueError("userId must not contain '|'")
        if "|" in sid:
            raise ValueError("sessionId must not contain '|'")
        mtype = str(data.get("type") or "text").strip().lower()
        if mtype != "text":
            raise ValueError("Phase 1 supports type=text only")
        raw_content = data.get("content")
        text = ""
        if isinstance(raw_content, str):
            text = raw_content
        elif isinstance(raw_content, dict):
            text = str(raw_content.get("text") or "")
        elif raw_content is not None:
            text = str(raw_content)
        text = text.strip()

        attachments: List[ColaclawAttachmentRef] = []
        raw_att = data.get("attachments")
        if raw_att is not None:
            if not isinstance(raw_att, list):
                raise ValueError("attachments must be an array")
            if len(raw_att) > _MAX_ATTACHMENTS:
                raise ValueError(f"at most {_MAX_ATTACHMENTS} attachments supported")
            for item in raw_att:
                attachments.append(ColaclawAttachmentRef.from_item(item))

        if not text and not attachments:
            raise ValueError("content or attachments required")

        if attachments:
            kinds = {a.kind for a in attachments}
            if len(kinds) > 1:
                raise ValueError(
                    "attachments must share the same kind (all image or all file)"
                )

        meta = data.get("metadata")
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("metadata must be an object if present")
        return ColaclawInboundMessage(
            workspace_id=ws,
            user_id=uid,
            session_id=sid,
            type=mtype,
            content=text,
            metadata=dict(meta) if isinstance(meta, dict) else {},
            attachments=attachments,
        )


COLACLAW_CHAT_TRANSPORT = "colaclaw"


def composite_chat_id(workspace_id: str, user_id: str, session_id: str) -> str:
    """Stable ColaClaw-only chat key for Hermes session isolation (Phase 9).

    Uses ``|`` (not ``:``) between segments so the id stays one token inside
    ``agent:main:colaclaw:dm:{chat_id}`` — colons inside ``chat_id`` would break
    :func:`gateway.run._parse_session_key`.

    Format: ``colaclaw|{workspace_id}|{user_id}|{session_id}``.
    Legacy ``workspace:session`` (single colon, no ``colaclaw|`` prefix) remains
    supported in :meth:`ColaClawAdapter._resolve_ctx`.
    """
    if ":" in workspace_id:
        raise ValueError("workspaceId must not contain ':'")
    if ":" in user_id:
        raise ValueError("userId must not contain ':'")
    if ":" in session_id:
        raise ValueError("sessionId must not contain ':'")
    if "|" in workspace_id:
        raise ValueError("workspaceId must not contain '|'")
    if "|" in user_id:
        raise ValueError("userId must not contain '|'")
    if "|" in session_id:
        raise ValueError("sessionId must not contain '|'")
    return f"{COLACLAW_CHAT_TRANSPORT}|{workspace_id}|{user_id}|{session_id}"
