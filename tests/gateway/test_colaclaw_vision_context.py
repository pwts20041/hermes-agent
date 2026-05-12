"""Source-aware labels for ColaClaw vs Telegram vision fallbacks."""

from gateway.config import Platform
from gateway.platforms.colaclaw.vision_context import attachment_source_label_for_vision


def test_attachment_source_label_for_vision():
    assert attachment_source_label_for_vision(Platform.TELEGRAM) == "Telegram"
    assert attachment_source_label_for_vision(Platform.COLACLAW) == "ColaClaw"
    assert attachment_source_label_for_vision(None) == "your chat"
