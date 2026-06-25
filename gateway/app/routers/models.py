"""``/v1/models`` — the model catalogue Zoo Code reads to validate the model id.

We serve the catalogue from the gateway's own configuration (the public model
ids in ``MODEL_ALIASES`` / ``DEFAULT_MODEL``) rather than proxying the engine, so
the names clients see are the gateway-facing aliases — not whatever internal id
the engine happens to use. This is the seam that makes model routing work.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import authenticate
from ..config import get_settings
from ..errors import openai_error

router = APIRouter(prefix="/v1", tags=["models"])

# A fixed creation timestamp keeps the catalogue deterministic across restarts
# (the value is cosmetic; OpenAI clients only read the id).
_CREATED = 1_700_000_000


def _model_object(model_id: str) -> dict:
    return {
        "id": model_id,
        "object": "model",
        "created": _CREATED,
        "owned_by": get_settings().service_name,
    }


@router.get("/models")
async def list_models(_: str = Depends(authenticate)):
    s = get_settings()
    data = [_model_object(mid) for mid in s.model_map.keys()]
    return {"object": "list", "data": data}


@router.get("/models/{model_id:path}")
async def retrieve_model(model_id: str, _: str = Depends(authenticate)):
    s = get_settings()
    if model_id not in s.model_map and not s.allow_unlisted_models:
        raise HTTPException(
            status_code=404,
            detail=openai_error(
                f"Model '{model_id}' not found.",
                err_type="invalid_request_error",
                code="model_not_found",
            ),
        )
    return _model_object(model_id)
