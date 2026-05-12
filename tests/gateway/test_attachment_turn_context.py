"""Tests for current-turn attachment grounding (all platforms)."""

from __future__ import annotations

from gateway.config import Platform
from gateway.inbound_attachment_context import (
    build_attachment_priority_system_note,
    build_current_turn_attachments_preamble,
    normalize_message_type_for_media,
    safe_attachment_log_dict,
)
from gateway.platforms.base import MessageEvent, MessageType, merge_pending_message_event
from gateway.session import SessionSource


def _src(platform: Platform = Platform.COLACLAW) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id="colaclaw|ws|u|sess",
        user_id="u",
        chat_type="dm",
    )


def test_normalize_pdf_paths_sets_document_not_text():
    ev = MessageEvent(
        text="summarize",
        message_type=MessageType.TEXT,
        source=_src(),
        media_urls=["/tmp/cache/doc_ws_u_report.pdf"],
        media_types=["application/pdf"],
    )
    normalize_message_type_for_media(ev)
    assert ev.message_type == MessageType.DOCUMENT


def test_normalize_images_sets_photo():
    ev = MessageEvent(
        text="what is this",
        message_type=MessageType.TEXT,
        source=_src(),
        media_urls=["/tmp/a.png"],
        media_types=["image/png"],
    )
    normalize_message_type_for_media(ev)
    assert ev.message_type == MessageType.PHOTO


def test_preamble_lists_paths_and_mime():
    ev = MessageEvent(
        text="go",
        message_type=MessageType.DOCUMENT,
        source=_src(),
        media_urls=["/cache/x_ws_u_monthly.xlsx"],
        media_types=[
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ],
    )
    pre = build_current_turn_attachments_preamble(ev, platform_key="colaclaw")
    assert "PRIMARY source" in pre
    assert "/cache/x_ws_u_monthly.xlsx" in pre
    assert "spreadsheetml" in pre
    assert "monthly.xlsx" in pre or "xlsx" in pre


def test_safe_attachment_log_no_secrets_in_structured_payload():
    ev = MessageEvent(
        text="x",
        message_type=MessageType.DOCUMENT,
        source=_src(),
        media_urls=["/path/secret_token_file.pdf"],
        media_types=["application/pdf"],
    )
    d = safe_attachment_log_dict(ev)
    assert d["attachment_context_count"] == 1
    assert d["agent_context_includes_attachments"] is True
    assert "secret_token" not in str(d.values())


def test_merge_pending_text_then_document_sets_document():
    pending: dict = {}
    session_key = "sk1"
    t1 = MessageEvent(
        text="hi",
        message_type=MessageType.TEXT,
        source=_src(Platform.TELEGRAM),
    )
    d1 = MessageEvent(
        text="",
        message_type=MessageType.DOCUMENT,
        source=_src(Platform.TELEGRAM),
        media_urls=["/t/r.pdf"],
        media_types=["application/pdf"],
    )
    merge_pending_message_event(pending, session_key, t1)
    merge_pending_message_event(pending, session_key, d1)
    merged = pending[session_key]
    assert merged.message_type == MessageType.DOCUMENT
    assert merged.media_urls == ["/t/r.pdf"]
    assert "hi" in merged.text


def test_system_note_contains_platform():
    s = build_attachment_priority_system_note(
        attachment_count=2, platform_key="colaclaw"
    )
    assert "2" in s
    assert "colaclaw" in s
    assert "priorit" in s.lower()


def test_merge_colaclaw_pending_media_with_text_interrupt():
    pending: dict = {}
    sk = "k"
    doc = MessageEvent(
        text="",
        message_type=MessageType.DOCUMENT,
        source=_src(),
        media_urls=["/c/report.pdf"],
        media_types=["application/pdf"],
    )
    follow = MessageEvent(
        text="summarize for me",
        message_type=MessageType.TEXT,
        source=_src(),
    )
    merge_pending_message_event(pending, sk, doc)
    merge_pending_message_event(pending, sk, follow, merge_text=True)
    m = pending[sk]
    assert m.message_type == MessageType.DOCUMENT
    assert m.media_urls == ["/c/report.pdf"]
    assert "summarize" in m.text
