"""API-key authentication.

Authentication is intentionally simple and stateless: a static set of bearer
tokens supplied via ``GATEWAY_API_KEYS``. This is the right altitude for a
self-hosted single-tenant gateway feeding a tool like Zoo Code — no user db, no
OAuth dance — while still giving you per-key analytics, rate limiting and the
ability to revoke a leaked key by editing one env var.

Keys are compared in constant time and surfaced everywhere as a short, stable,
non-reversible ``key_id`` (first 8 chars of a SHA-256) so the raw secret never
lands in logs or the analytics database.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status

from .config import Settings, get_settings
from .errors import openai_error
from .logging_config import api_key_id_ctx


def key_id(raw_key: str) -> str:
    """Return a stable, non-reversible identifier for an API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()[:8]


def _extract_bearer(authorization: str | None, x_api_key: str | None) -> str | None:
    """Accept either ``Authorization: Bearer <key>`` or ``x-api-key: <key>``."""
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    if x_api_key:
        return x_api_key.strip()
    return None


def _match(candidate: str, allowed: set[str]) -> bool:
    """Constant-time membership test.

    Both sides are SHA-256'd to a fixed 32-byte digest before comparison, so the
    comparison never leaks key length (``compare_digest`` is only constant-time
    for equal-length inputs), and we always scan the full set with no early exit,
    so timing never depends on which key (or whether any) matched.
    """
    cand = hashlib.sha256(candidate.encode()).digest()
    matched = False
    for key in allowed:
        if hmac.compare_digest(cand, hashlib.sha256(key.encode()).digest()):
            matched = True
    return matched


async def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """FastAPI dependency: validate the client key and return its ``key_id``.

    The resolved key id is stashed on ``request.state`` and in the logging
    context so middleware, rate limiting and analytics can all reference it.
    """
    settings: Settings = get_settings()

    # Escape hatch for trusted local development only.
    if not settings.require_auth and not settings.api_keys:
        kid = "anon"
        request.state.api_key_id = kid
        api_key_id_ctx.set(kid)
        return kid

    candidate = _extract_bearer(authorization, x_api_key)
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=openai_error(
                "Missing API key. Pass it as 'Authorization: Bearer <key>'.",
                err_type="invalid_request_error",
                code="missing_api_key",
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _match(candidate, settings.api_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=openai_error(
                "Invalid API key.",
                err_type="invalid_request_error",
                code="invalid_api_key",
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = key_id(candidate)
    request.state.api_key_id = kid
    api_key_id_ctx.set(kid)
    return kid


async def require_admin(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    """Guard the /admin/* endpoints with the dedicated admin key."""
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=openai_error(
                "Admin API is disabled (ADMIN_API_KEY not set).",
                err_type="invalid_request_error",
                code="admin_disabled",
            ),
        )
    candidate = _extract_bearer(authorization, x_api_key)
    if not candidate or not hmac.compare_digest(candidate, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=openai_error(
                "Invalid admin key.",
                err_type="invalid_request_error",
                code="invalid_admin_key",
            ),
        )
