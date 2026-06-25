"""``/v1/embeddings`` — optional, for Zoo Code's codebase-indexing / RAG.

Disabled-by-default in spirit: it simply forwards to the engine's embeddings
endpoint through the same relay. To use it, run an embedding model on the engine
(or a second engine) and add its id to ``MODEL_ALIASES`` so the gateway will
route to it. This keeps the gateway a single front door for both chat and
embeddings without special-casing either.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import authenticate
from ..errors import error_response
from ..relay import relay

router = APIRouter(prefix="/v1", tags=["embeddings"])


@router.post("/embeddings")
async def embeddings(request: Request, key_id: str = Depends(authenticate)):
    try:
        body = await request.json()
    except Exception:
        return error_response(400, "Request body must be valid JSON.",
                              code="invalid_json")
    if not isinstance(body, dict) or "input" not in body:
        return error_response(400, "Field 'input' is required.",
                              code="missing_input")
    # Embeddings are never streamed.
    body.pop("stream", None)
    return await relay(request, upstream_path="/embeddings", body=body, key_id=key_id)
