"""ColaClaw must not get the generic /sethome nag — no home-channel semantics."""

from gateway.config import Platform
from gateway.run import _should_offer_home_channel_onboarding


def test_colaclaw_skips_home_channel_prompt():
    assert _should_offer_home_channel_onboarding(Platform.COLACLAW) is False


def test_telegram_shows_home_channel_prompt():
    assert _should_offer_home_channel_onboarding(Platform.TELEGRAM) is True


def test_webhook_skips_home_channel_prompt():
    assert _should_offer_home_channel_onboarding(Platform.WEBHOOK) is False
