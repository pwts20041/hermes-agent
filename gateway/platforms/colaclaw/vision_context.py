"""Platform-aware phrasing for vision / attachment enrichment (ColaClaw vs Telegram)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gateway.config import Platform


def attachment_source_label_for_vision(platform: Optional["Platform"]) -> str:
    """Short label used when image enrichment fails or needs provenance context."""
    from gateway.config import Platform as _P

    if platform == _P.TELEGRAM:
        return "Telegram"
    if platform == _P.COLACLAW:
        return "ColaClaw"
    return "your chat"
