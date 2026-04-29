"""Shared slowapi Limiter.

Importing this module in a router lets it decorate endpoints with `@limiter.limit(...)`.
The limiter is attached to `app.state.limiter` in `app/main.py`, which is what slowapi
needs to resolve the decorator at request time.

Keying strategy:
- Default is the client IP (via `get_remote_address`), which handles both raw-socket
  and X-Forwarded-For when the deployment's proxy/ingress strips it into request.client.
- For password endpoints we also want a per-user cap — slowapi's per-function decorator
  supports a custom `key_func` kwarg so callers can pass `_user_key_func` below.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _user_key_func(request: Request) -> str:
    """Rate-limit key that includes the authenticated uid when available.

    `verify_firebase_token` deposits the current user on `request.state.current_user`
    (see `app.auth.dependencies.get_current_user`). If that has run we key on the uid;
    otherwise we fall back to IP so anonymous probes still get throttled.
    """
    current = getattr(request.state, "current_user", None)
    uid = getattr(current, "firebase_uid", None) if current else None
    if uid:
        return f"uid:{uid}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],  # no global limits — endpoints opt in explicitly
    headers_enabled=True,  # emit X-RateLimit-* headers so the FE can show countdowns
)
