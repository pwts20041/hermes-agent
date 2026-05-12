"""ColaClaw HTTP authentication (Phase 1 shared secret, Bearer token)."""

import hmac
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web

logger = logging.getLogger(__name__)


def verify_colaclaw_auth(
    request: "web.Request",
    expected_secret: str,
) -> Optional["web.Response"]:
    """
    Validate Authorization: Bearer <secret> when secret is configured.

    If expected_secret is empty, authentication is skipped (local dev only);
    logs a warning once per process is not worth it — log on each startup in adapter.

    Returns None if OK, or a JSON 401 web.Response.
    """
    from aiohttp import web

    if not expected_secret:
        return None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if hmac.compare_digest(token, expected_secret):
            return None

    logger.warning("[colaclaw] Rejected request: invalid or missing bearer token")
    return web.json_response({"error": "unauthorized"}, status=401)
