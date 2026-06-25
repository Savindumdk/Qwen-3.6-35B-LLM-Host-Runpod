"""``/v1/completions`` — legacy text-completion endpoint.

Kept for compatibility with tools and codebase-indexing flows that still use the
non-chat completion API. Same relay pipeline as chat; only the upstream path and
the required field differ.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticate
from ..errors import error_response
from ..relay import relay

router = APIRouter(prefix="/v1", tags=["completions"])


@router.post("/completions")
async def completions(request: Request, key_id: str = Depends(authenticate)):
    try:
        body = await request.json()
    except Exception:
        return error_response(400, "Request body must be valid JSON.",
                              code="invalid_json")
    if not isinstance(body, dict) or "prompt" not in body:
        return error_response(400, "Field 'prompt' is required.",
                              code="missing_prompt")
    return await relay(request, upstream_path="/completions", body=body, key_id=key_id)
