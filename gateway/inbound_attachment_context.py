"""Current-turn inbound attachment context (Telegram, ColaClaw, and other platforms).

Normalized helpers keep MessageEvent media aligned with how ``gateway.run``
preprocesses vision, documents, and agent prompts — without platform-specific
parallel logic beyond logging labels.
"""

from __future__ import annotations

import mimetypes
import os
import re
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from gateway.platforms.base import MessageEvent


def normalize_message_type_for_media(event: "MessageEvent") -> None:
    """If ``media_urls`` is non-empty, set PHOTO vs DOCUMENT from MIME/path.

    Merges and race paths can leave ``message_type=TEXT`` while paths are
    present; document preprocessing and tool routing then skip attachments.
    """
    from gateway.platforms.base import MessageType

    if not event.media_urls:
        return
    if event.message_type in (
        MessageType.VOICE,
        MessageType.AUDIO,
        MessageType.VIDEO,
    ):
        return

    all_image = True
    for i, path in enumerate(event.media_urls):
        mtype_raw = event.media_types[i] if i < len(event.media_types) else ""
        mtype = (mtype_raw or "").strip().split(";")[0].strip().lower()
        if not mtype:
            guessed, _ = mimetypes.guess_type(path)
            mtype = (guessed or "").lower()
        is_img = mtype.startswith("image/")
        if not is_img:
            all_image = False
            break

    if all_image:
        event.message_type = MessageType.PHOTO
    else:
        event.message_type = MessageType.DOCUMENT


def display_name_for_cache_path(path: str) -> str:
    basename = os.path.basename(path)
    parts = basename.split("_", 2)
    display_name = parts[2] if len(parts) >= 3 else basename
    return re.sub(r"[^\w.\- ]", "_", display_name)


def build_current_turn_attachments_preamble(
    event: "MessageEvent",
    *,
    platform_key: str,
) -> str:
    """Build a user-turn preamble that lists hydrated local paths (primary context)."""
    lines: List[str] = [
        "[Current turn includes uploaded attachments — treat them as the PRIMARY source "
        "for this user request.",
        "",
        "Before searching the workspace, repository files, or long-term memories for unrelated "
        "material, read or analyze these local paths with the same tools you use for messaging "
        "platform file uploads (read_file, spreadsheet/CSV tools when applicable, "
        "vision_analyze for images; if read_file cannot read a binary such as PDF, try "
        "vision_analyze with the same local path as image_url where the model supports it).",
        "",
        "Do not tell the user no file was attached when this block is present. "
        "Do not instruct switching to another chat app to answer.]",
        "",
        f"Attachments ({len(event.media_urls)}) — source: {platform_key}",
    ]
    for i, path in enumerate(event.media_urls, start=1):
        mtype_raw = event.media_types[i - 1] if i - 1 < len(event.media_types) else ""
        mtype = (mtype_raw or "").strip().split(";")[0].strip().lower()
        if not mtype:
            guessed, _ = mimetypes.guess_type(path)
            mtype = (guessed or "application/octet-stream").lower()
        name = display_name_for_cache_path(path)
        lines.append(f"{i}. {name}")
        lines.append(f"   - type: {mtype}")
        lines.append(f"   - local path: {path}")
    lines.append("")
    lines.append(
        "[End of attachment list — the user's wording below refers to these files unless they "
        "explicitly point elsewhere.]"
    )
    return "\n".join(lines)


def build_attachment_priority_system_note(*, attachment_count: int, platform_key: str) -> str:
    """Short system-prompt addendum for attachment-first behavior."""
    return (
        f"[SYSTEM: This turn includes {attachment_count} hydrated inbound attachment(s) "
        f"from {platform_key}. Prioritize reading or analyzing those local paths before "
        "inventing answers from unrelated project context or older chat transcripts.]"
    )


def safe_attachment_log_dict(event: "MessageEvent") -> Dict[str, Any]:
    """Structured log fields only — no signed URLs or user message content."""
    types: List[str] = []
    for i, _path in enumerate(event.media_urls or ()):
        raw = event.media_types[i] if i < len(event.media_types or ()) else ""
        mt = (raw or "").strip().split(";")[0].strip().lower() or "unknown"
        types.append(mt)
    n = len(event.media_urls or ())
    return {
        "attachment_context_count": n,
        "attachment_context_paths_count": n,
        "attachment_context_types": types,
        "agent_context_includes_attachments": bool(n),
    }
