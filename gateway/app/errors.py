"""OpenAI-compatible error envelopes.

Zoo Code (and any OpenAI SDK) expects errors in the shape
``{"error": {"message": ..., "type": ..., "code": ...}}``. Returning that exact
structure means client-side error handling, retries and messages all work as if
they were talking to OpenAI directly.
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def openai_error(
    message: str,
    err_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    """Build the ``error`` body OpenAI clients understand."""
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        }
    }


def error_response(
    status_code: int,
    message: str,
    err_type: str = "invalid_request_error",
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return a JSONResponse carrying an OpenAI-style error envelope."""
    return JSONResponse(
        status_code=status_code,
        content=openai_error(message, err_type=err_type, code=code),
        headers=headers,
    )


# Convenience constructors for the statuses we raise most often.
def upstream_unavailable(detail: str) -> JSONResponse:
    return error_response(
        status.HTTP_502_BAD_GATEWAY,
        f"Inference engine unavailable: {detail}",
        err_type="api_error",
        code="upstream_unavailable",
    )


def upstream_timeout(detail: str) -> JSONResponse:
    return error_response(
        status.HTTP_504_GATEWAY_TIMEOUT,
        f"Inference engine timed out: {detail}",
        err_type="api_error",
        code="upstream_timeout",
    )
