"""Deliver ColaClaw callbacks over HTTPS (Phase 2: retries, v2 logging)."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


async def post_callback(
    session,
    callback_url: str,
    payload: Dict[str, Any],
    *,
    secret: str = "",
    timeout_seconds: float = 60.0,
    max_retries: int = 1,
    retry_delay_seconds: float = 1.5,
) -> Tuple[bool, Optional[str]]:
    """
    POST JSON to ColaClaw callback URL.

    Retries at most *max_retries* times on failure (transient or HTTP error)
    with *retry_delay_seconds* between attempts — bounded to avoid storms.

    Returns (success, error_message).
    """
    import aiohttp

    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    attempts = max(0, int(max_retries)) + 1
    last_err: Optional[str] = None

    for attempt in range(attempts):
        if attempt > 0:
            await asyncio.sleep(retry_delay_seconds)
            logger.info(
                "[colaclaw] Callback retry %d/%d for sessionId=%s",
                attempt,
                attempts - 1,
                payload.get("sessionId", ""),
            )
        try:
            async with session.post(
                callback_url,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    last_err = f"callback HTTP {resp.status}: {text[:500]}"
                    logger.warning("[colaclaw] %s", last_err)
                    continue
                _log_success(payload)
                return True, None
        except Exception as e:
            last_err = str(e)
            logger.error("[colaclaw] Callback failed (attempt %d): %s", attempt + 1, e)
            continue

    return False, last_err


def _log_success(payload: Dict[str, Any]) -> None:
    """Log without assuming Phase 1 vs v2 shape."""
    sid = payload.get("sessionId", "")
    if "type" in payload and "version" in payload:
        ptype = payload.get("type", "")
        seq = payload.get("sequence", "")
        etext = ""
        c = payload.get("content")
        if isinstance(c, dict):
            etext = str(c.get("text", ""))
        logger.info(
            "[colaclaw] Callback delivered v2 type=%s sequence=%s sessionId=%s text_len=%d",
            ptype,
            seq,
            sid,
            len(etext),
        )
    else:
        logger.info(
            "[colaclaw] Callback delivered legacy sessionId=%s chars=%d",
            sid,
            len(str(payload.get("content", ""))),
        )
