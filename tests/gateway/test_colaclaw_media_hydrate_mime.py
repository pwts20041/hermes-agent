"""ColaClaw media hydration: MIME normalization + Telegram-parity MessageEvent fields."""

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.platforms.colaclaw import media_hydration as mh
from gateway.platforms.colaclaw.contract import ColaclawAttachmentRef
from gateway.session import SessionSource


def _minimal_jpeg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x1b\x14\x15\x19\x1a\x1f\x1e\x1b"
        b"\x1c\x1e\x1c\x32\x24\x21\x22\x24\x2e\x36\x2e\x2c\x2c\x2e\x45\x43\x38"
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14"
        b"\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03"
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x55\xff\xd9"
    )


@pytest.mark.asyncio
async def test_hydrate_image_sets_photo_and_normalizes_mime(monkeypatch):
    jpeg = _minimal_jpeg()

    async def _fake_fetch(_url: str) -> bytes:
        return jpeg

    monkeypatch.setattr(mh, "_fetch_attachment_bytes", _fake_fetch)

    src = SessionSource(
        platform=Platform.COLACLAW,
        chat_id="colaclaw|w|u|s",
        user_id="u",
        chat_type="dm",
    )
    event = MessageEvent(
        text="caption",
        message_type=MessageType.TEXT,
        source=src,
    )
    ref = ColaclawAttachmentRef(
        download_url="https://tenant.example/att/dl",
        mime_type="IMAGE/JPEG; charset=binary",
        kind="image",
        file_name="x.jpg",
    )
    await mh.hydrate_colaclaw_attachments_to_event(event, [ref])
    assert event.message_type == MessageType.PHOTO
    assert len(event.media_urls) == 1
    assert event.media_types == ["image/jpeg"]
    assert event.media_urls[0].endswith(".jpg")


def test_colaclaw_attachment_ref_from_item_normalizes_mime():
    ref = ColaclawAttachmentRef.from_item(
        {
            "downloadUrl": "https://x.test/a",
            "mimeType": "Image/PNG",
            "kind": "image",
            "fileName": "a.png",
        }
    )
    assert ref.mime_type == "image/png"
