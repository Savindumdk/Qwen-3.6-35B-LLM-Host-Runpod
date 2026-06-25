"""``/v1/chat/completions`` — the endpoint Zoo Code actually drives.

This is intentionally a thin wrapper: parse and minimally validate the body,
then hand off to :func:`app.relay.relay`, which owns routing, rate limiting,
streaming and analytics. Tool calls, ``reasoning_content`` and multi-part
content all pass through untouched because the relay never rewrites the engine's
output shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticate
from ..errors import error_response
from ..relay import relay

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions")
async def chat_completions(request: Request, key_id: str = Depends(authenticate)):
    try:
        body = await request.json()
    except Exception:
        return error_response(400, "Request body must be valid JSON.",
                              code="invalid_json")
    if not isinstance(body, dict) or not body.get("messages"):
        return error_response(
            400, "Field 'messages' is required and must be a non-empty array.",
            code="missing_messages",
        )
    return await relay(request, upstream_path="/chat/completions", body=body, key_id=key_id)
