"""Phase 2 ColaClaw structured callback tests."""

import pytest

from gateway.platforms.colaclaw.contract import (
    ASSISTANT_ERROR,
    ASSISTANT_MESSAGE,
    ASSISTANT_PROGRESS,
    CALLBACK_VERSION,
    RESERVED_EVENT_TYPES,
    build_legacy_flat_payload,
    build_v2_callback_payload,
    classify_assistant_event_type,
    is_legacy_callback_schema,
)


def test_classify_message_default():
    assert classify_assistant_event_type(None) == ASSISTANT_MESSAGE
    assert classify_assistant_event_type({}) == ASSISTANT_MESSAGE


def test_classify_progress_and_status():
    assert (
        classify_assistant_event_type({"hermes_outbound_kind": "progress"})
        == ASSISTANT_PROGRESS
    )
    assert (
        classify_assistant_event_type({"hermes_outbound_kind": "status"})
        == ASSISTANT_PROGRESS
    )


def test_classify_error():
    assert (
        classify_assistant_event_type({"hermes_outbound_kind": "error"})
        == ASSISTANT_ERROR
    )


def test_v2_payload_required_fields():
    p = build_v2_callback_payload(
        workspace_id="w",
        session_id="s",
        user_id="u",
        event_type=ASSISTANT_MESSAGE,
        sequence=3,
        text="hi",
        status="ok",
        event_id="fixed-id",
    )
    assert p["version"] == CALLBACK_VERSION
    assert p["eventId"] == "fixed-id"
    assert p["workspaceId"] == "w"
    assert p["sessionId"] == "s"
    assert p["userId"] == "u"
    assert p["source"] == "hermes"
    assert p["type"] == ASSISTANT_MESSAGE
    assert p["sequence"] == 3
    assert p["content"]["text"] == "hi"
    assert p["status"] == "ok"
    assert "createdAt" in p


def test_legacy_flat_payload():
    p = build_legacy_flat_payload(
        workspace_id="w",
        session_id="s",
        user_id="u",
        content="legacy",
    )
    assert set(p.keys()) == {"workspaceId", "sessionId", "userId", "type", "content"}
    assert p["content"] == "legacy"


@pytest.mark.parametrize(
    "raw,legacy",
    [
        ("legacy", True),
        ("phase1", True),
        ("v1", True),
        ("v2", False),
        ("", False),
    ],
)
def test_legacy_schema_extra(monkeypatch, raw, legacy):
    monkeypatch.delenv("COLACLAW_CALLBACK_SCHEMA", raising=False)
    extra = {"callback_schema": raw} if raw else {}
    assert is_legacy_callback_schema(extra) is legacy


def test_legacy_schema_env_overrides_default(monkeypatch):
    monkeypatch.setenv("COLACLAW_CALLBACK_SCHEMA", "legacy")
    assert is_legacy_callback_schema({}) is True
    assert is_legacy_callback_schema({"callback_schema": "v2"}) is False


def test_reserved_types_documented():
    assert "assistant.stream_delta" in RESERVED_EVENT_TYPES
