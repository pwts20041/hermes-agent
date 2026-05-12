"""Phase 10E: download ColaClaw attachment URLs into Hermes media cache (Telegram parity).

ColaClaw SaaS stores blobs and sends time-limited signed HTTPS URLs. Hermes
fetches bytes, writes to the same image/document caches used by Telegram, and
fills :class:`~gateway.platforms.base.MessageEvent` ``media_urls`` /
``media_types`` so ``gateway.run`` vision / document enrichment runs unchanged.

**Local / split-stack dev:** URLs may point at ``localhost`` or private hosts,
which :func:`tools.url_safety.is_safe_url` blocks. Set ``COLACLAW_MEDIA_FETCH_HOSTS``
to a comma-separated hostname allowlist (e.g. ``127.0.0.1,localhost``). Omit in
production when ColaClaw is on a public HTTPS origin.
"""

from __future__ import annotations

import logging
import os
from typing import List

import httpx

from gateway.platforms.base import (
    MessageEvent,
    MessageType,
    SUPPORTED_DOCUMENT_TYPES,
    cache_document_from_bytes,
    cache_image_from_bytes,
)
from tools.url_safety import is_safe_url

from .contract import ColaclawAttachmentRef

logger = logging.getLogger(__name__)

_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _normalize_mime(mime: str) -> str:
    """Lowercase + strip parameters so ``IMAGE/JPEG`` matches vision routing."""
    return (mime or "").strip().split(";")[0].strip().lower()


def _normalize_media_fetch_allowlist_entry(raw: str) -> str:
    """Strip whitespace, optional scheme, paths — so ``https://host/foo`` works."""
    from urllib.parse import urlparse

    s = raw.strip()
    if not s:
        return ""
    if "://" in s:
        host = (urlparse(s).hostname or "").strip().lower()
        return host
    return s.split("/")[0].strip().lower()


def _colaclaw_url_fetch_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    allow_raw = (os.getenv("COLACLAW_MEDIA_FETCH_HOSTS") or "").strip()
    if allow_raw:
        allowed_hosts = {
            _normalize_media_fetch_allowlist_entry(h)
            for h in allow_raw.split(",")
            if h.strip()
        }
        allowed_hosts.discard("")
        if host in allowed_hosts:
            return True
    return is_safe_url(url)


async def _fetch_attachment_bytes(url: str) -> bytes:
    if not _colaclaw_url_fetch_allowed(url):
        raise ValueError("attachment URL failed SSRF safety check")
    async with httpx.AsyncClient(
        timeout=120.0,
        follow_redirects=False,
    ) as client:
        response = await client.get(
            url,
            headers={"User-Agent": "Hermes-ColaClaw-Attachment/1.0"},
        )
        response.raise_for_status()
        return response.content


def _image_extension(mime_type: str, file_name: str | None) -> str:
    m = (mime_type or "").lower().strip().split(";")[0].strip()
    if m in _IMAGE_EXT_BY_MIME:
        return _IMAGE_EXT_BY_MIME[m]
    if file_name:
        import os as _os

        _, ext = _os.path.splitext(file_name)
        if ext:
            return ext.lower()
    return ".jpg"


def _safe_document_basename(file_name: str | None, mime_type: str) -> str:
    import os as _os

    base = _os.path.basename(file_name or "document").strip() or "document"
    ext = _os.path.splitext(base)[1].lower()
    if ext in SUPPORTED_DOCUMENT_TYPES:
        return base
    for cand_ext, cand_mime in SUPPORTED_DOCUMENT_TYPES.items():
        if cand_mime == (mime_type or "").strip().lower():
            stem = _os.path.splitext(base)[0] or "document"
            return f"{stem}{cand_ext}"
    raise ValueError(
        f"unsupported document type for Hermes cache (filename={base!r} mime={mime_type!r})"
    )


async def hydrate_colaclaw_attachments_to_event(
    event: MessageEvent,
    attachments: List[ColaclawAttachmentRef],
) -> None:
    if not attachments:
        return

    kinds = {a.kind for a in attachments}
    if len(kinds) != 1:
        raise ValueError("attachments must share the same kind (image or file)")
    only_kind = next(iter(kinds))
    if only_kind == "image":
        event.message_type = MessageType.PHOTO
    else:
        event.message_type = MessageType.DOCUMENT

    for i, att in enumerate(attachments):
        try:
            data = await _fetch_attachment_bytes(att.download_url)
        except Exception as exc:
            logger.warning(
                "colaclaw attachment fetch failed idx=%d kind=%s: %s",
                i,
                att.kind,
                exc,
            )
            raise ValueError("could not download one or more attachments") from exc

        if att.kind == "image":
            ext = _image_extension(att.mime_type, att.file_name)
            path = cache_image_from_bytes(data, ext=ext)
            event.media_urls.append(path)
            event.media_types.append(
                _normalize_mime(att.mime_type) or f"image/{ext.lstrip('.')}",
            )
        else:
            basename = _safe_document_basename(att.file_name, att.mime_type)
            path = cache_document_from_bytes(data, basename)
            event.media_urls.append(path)
            doc_mime = _normalize_mime(att.mime_type) or "application/octet-stream"
            event.media_types.append(doc_mime)

    logger.info(
        "[colaclaw] Hydrated %d attachment(s) as %s → %d local path(s)",
        len(attachments),
        event.message_type.value,
        len(event.media_urls),
    )
