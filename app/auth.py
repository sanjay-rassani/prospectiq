"""Auth gate when binding beyond localhost (P10-7)."""

from __future__ import annotations

import hmac
import logging
import secrets
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings

logger = logging.getLogger(__name__)

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def requires_auth(settings: Settings) -> bool:
    """Auth activates only when the configured bind host is not loopback."""
    host = (settings.host or "").strip().lower()
    return bool(host) and host not in _LOOPBACK


def resolve_auth_secret(settings: Settings) -> str:
    """Return the shared secret, generating an ephemeral one if needed."""
    secret = (settings.auth_token or "").strip()
    if secret:
        return secret
    if requires_auth(settings):
        secret = secrets.token_urlsafe(24)
        logger.warning(
            "HOST=%s is not loopback — auth gate ON. One-time token: %s "
            "(set AUTH_TOKEN in .env to make it stable)",
            settings.host,
            secret,
        )
        return secret
    return ""


class LocalhostAuthGate(BaseHTTPMiddleware):
    """Simple shared-secret cookie gate for non-loopback binds."""

    def __init__(self, app: object, settings: Settings, secret: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.settings = settings
        self.enabled = requires_auth(settings)
        self.secret = secret

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        if path in {"/health", "/login", "/logout"} or path.startswith("/static"):
            return await call_next(request)
        cookie = request.cookies.get("prospectiq_auth", "")
        if self.secret and cookie and hmac.compare_digest(cookie, self.secret):
            return await call_next(request)
        return RedirectResponse(url="/login", status_code=303)
