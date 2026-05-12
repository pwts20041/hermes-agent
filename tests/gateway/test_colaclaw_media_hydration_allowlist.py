"""COLACLAW_MEDIA_FETCH_HOSTS parsing (hostnames, optional https:// prefix)."""

import pytest

from gateway.platforms.colaclaw import media_hydration as mh


def test_fetch_allowed_strip_scheme_and_path_from_allowlist(monkeypatch):
    monkeypatch.setenv(
        "COLACLAW_MEDIA_FETCH_HOSTS",
        "https://newsletter-wisconsin-dana-wma.trycloudflare.com/some/path,",
    )
    assert (
        mh._colaclaw_url_fetch_allowed(
            "https://newsletter-wisconsin-dana-wma.trycloudflare.com/api/chat/attachments/x/download?exp=1&sig=y",
        )
        is True
    )


def test_fetch_allowed_plain_hostname_in_allowlist(monkeypatch):
    monkeypatch.setenv(
        "COLACLAW_MEDIA_FETCH_HOSTS",
        "my-dev-box.internal",
    )
    assert (
        mh._colaclaw_url_fetch_allowed("https://my-dev-box.internal/file") is True
    )


@pytest.mark.parametrize("bad", ["", "   "])
def test_fetch_allowed_empty_entry_ignored(monkeypatch, bad):
    monkeypatch.setenv("COLACLAW_MEDIA_FETCH_HOSTS", bad)
    assert mh._colaclaw_url_fetch_allowed("https://127.0.0.1/foo") is False
