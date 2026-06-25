"""Cross-cutting HTTP middleware: request ids, timing, body limits, access logs.

This middleware threads a request id through the logging context, enforces the
max body size, and emits one access-log line per request. It deliberately does
**not** persist analytics rows: for streamed responses the body is still being
generated when middleware regains control after ``call_next``, so token usage
and true end-to-end latency aren't known yet. The inference route handlers own
analytics (see :mod:`app.analytics`) because they observe the precise completion
point — including the final ``usage`` chunk of a stream.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings
from .errors import error_response
from .logging_config import (
    api_key_id_ctx,
    get_logger,
    request_id_ctx,
)

logger = get_logger("gateway.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # Stable per-request id (honour an inbound one for trace propagation).
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        token_rid = request_id_ctx.set(rid)
        token_kid = api_key_id_ctx.set(None)

        # Defaults the route handler may overwrite via request.state.
        request.state.api_key_id = None
        request.state.model = None
        request.state.streamed = False
        request.state.prompt_tokens = 0
        request.state.completion_tokens = 0
        request.state.total_tokens = 0
        request.state.ttft_ms = None
        request.state.error = None

        # Enforce the body-size ceiling early (defends the proxy from abuse).
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_request_bytes:
            request_id_ctx.reset(token_rid)
            api_key_id_ctx.reset(token_kid)
            return error_response(
                413,
                f"Request body exceeds {settings.max_request_bytes} bytes.",
                err_type="invalid_request_error",
                code="payload_too_large",
            )

        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._access_log(request, status_code, latency_ms)
            request_id_ctx.reset(token_rid)
            api_key_id_ctx.reset(token_kid)

    @staticmethod
    def _access_log(request: Request, status_code: int, latency_ms: float):
        # For streamed responses this latency measures time-to-headers, not the
        # full generation; the authoritative number is in the analytics row the
        # handler writes. This line is a lightweight HTTP-layer access log.
        logger.info(
            "request",
            extra={
                "ctx_method": request.method,
                "ctx_path": request.url.path,
                "ctx_status": status_code,
                "ctx_latency_ms": round(latency_ms, 1),
                "ctx_model": getattr(request.state, "model", None),
                "ctx_streamed": getattr(request.state, "streamed", False),
            },
        )
