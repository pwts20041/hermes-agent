"""Phase 1 ColaClaw contract tests."""

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.colaclaw.adapter import ColaClawAdapter
from gateway.platforms.colaclaw.contract import (
    ColaclawInboundMessage,
    composite_chat_id,
    parse_callback_payload,
)


def test_inbound_from_payload_minimal():
    msg = ColaclawInboundMessage.from_payload(
        {
            "workspaceId": "ws_123",
            "userId": "user_123",
            "sessionId": "sess_123",
            "type": "text",
            "content": "Hello Hermes",
            "metadata": {},
        }
    )
    assert msg.workspace_id == "ws_123"
    assert msg.user_id == "user_123"
    assert msg.session_id == "sess_123"
    assert msg.content == "Hello Hermes"


def test_inbound_content_dict():
    msg = ColaclawInboundMessage.from_payload(
        {
            "workspaceId": "ws",
            "userId": "u",
            "sessionId": "s",
            "content": {"text": "hi"},
        }
    )
    assert msg.content == "hi"


def test_composite_chat_id_shape():
    assert composite_chat_id("ws", "u", "s") == "colaclaw|ws|u|s"


def test_composite_chat_id_rejects_workspace_with_colon():
    with pytest.raises(ValueError):
        composite_chat_id("bad:ws", "u", "s")


def test_composite_chat_id_rejects_workspace_with_pipe():
    with pytest.raises(ValueError):
        composite_chat_id("bad|ws", "u", "s")


def test_resolve_ctx_pipe_composite_and_legacy():
    adapter = ColaClawAdapter(PlatformConfig())
    cid = composite_chat_id("w", "u", "s")
    assert cid == "colaclaw|w|u|s"
    assert adapter._resolve_ctx(cid) == {
        "workspace_id": "w",
        "user_id": "u",
        "session_id": "s",
    }
    assert adapter._resolve_ctx("oldws:oldsess") == {
        "workspace_id": "oldws",
        "user_id": "",
        "session_id": "oldsess",
    }


def test_inbound_with_image_attachments():
    msg = ColaclawInboundMessage.from_payload(
        {
            "workspaceId": "ws",
            "userId": "u",
            "sessionId": "s",
            "content": "",
            "attachments": [
                {
                    "downloadUrl": "https://app.example.com/api/chat/attachments/x/download?exp=1&sig=y",
                    "mimeType": "image/png",
                    "kind": "image",
                    "fileName": "a.png",
                }
            ],
        }
    )
    assert msg.content == ""
    assert len(msg.attachments) == 1
    assert msg.attachments[0].kind == "image"
    assert msg.attachments[0].file_name == "a.png"
    assert "app.example.com" in msg.attachments[0].download_url


def test_callback_payload_shape():
    p = parse_callback_payload(
        workspace_id="ws",
        session_id="s",
        user_id="u",
        content="reply",
    )
    assert p["workspaceId"] == "ws"
    assert p["sessionId"] == "s"
    assert p["userId"] == "u"
    assert p["type"] == "message"
    assert p["content"] == "reply"
