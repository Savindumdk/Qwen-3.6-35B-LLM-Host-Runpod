"""Shared relay pipeline for chat/completions and legacy completions.

Both endpoints funnel through :func:`relay` so model routing, rate-limit
admission, streaming, usage accounting and analytics behave identically. The
endpoint modules are thin wrappers that only differ in the upstream path and a
light request-shape check.

Streaming is handled as a true pass-through: we relay each SSE frame the engine
emits unmodified (so tool-call deltas and ``reasoning_content`` survive) while
sniffing the terminal ``usage`` frame for accounting. The rate-limit slot is held
for the whole stream and released — with real token usage reconciled — in the
generator's ``finally`` block, which runs even if the client disconnects early.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from . import analytics, proxy
from .config import get_settings
from .errors import error_response, openai_error
from .logging_config import get_logger
from .rate_limit import RateLimitError

logger = get_logger("gateway.relay")

# Headers that keep SSE flowing through buffering reverse proxies (nginx, the
# RunPod/Cloudflare edge). ``X-Accel-Buffering: no`` disables nginx buffering.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}


def _resolve_or_error(request: Request, body: dict) -> tuple[str | None, str | None, Response | None]:
    """Return (public_model, upstream_model, error_response)."""
    s = get_settings()
    requested = body.get("model")
    upstream = s.resolve_model(requested)
    if upstream is None:
        known = ", ".join(sorted(s.model_map.keys()))
        return (
            requested,
            None,
            error_response(
                404,
                f"Model '{requested}' is not available. Known models: {known}.",
                err_type="invalid_request_error",
                code="model_not_found",
            ),
        )
    return (requested or s.default_model, upstream, None)


async def relay(
    request: Request,
    *,
    upstream_path: str,
    body: dict[str, Any],
    key_id: str,
) -> Response:
    s = get_settings()
    limiter = request.app.state.limiter

    public_model, upstream_model, err = _resolve_or_error(request, body)
    request.state.model = public_model
    if err is not None:
        analytics.record(
            request, status_code=404, latency_ms=0.0,
            model=public_model, streamed=False, error="model_not_found",
        )
        return err

    # Rewrite the model id to what the engine serves.
    body["model"] = upstream_model
    stream = bool(body.get("stream"))
    request.state.streamed = stream

    est = proxy.estimate_tokens(body)

    # ---- admission control ------------------------------------------------
    try:
        await limiter.acquire(key_id, est)
    except RateLimitError as e:
        analytics.record(
            request, status_code=429, latency_ms=0.0,
            model=public_model, streamed=stream, error="rate_limited",
        )
        headers = {"Retry-After": str(int(e.retry_after or 1))}
        return error_response(
            429, e.message, err_type="rate_limit_error",
            code="rate_limit_exceeded", headers=headers,
        )

    start = time.perf_counter()

    # ---- streaming --------------------------------------------------------
    if stream:
        if s.capture_stream_usage:
            opts = dict(body.get("stream_options") or {})
            opts.setdefault("include_usage", True)
            body["stream_options"] = opts

        async def event_stream():
            first_token = True
            ttft_ms: float | None = None
            usage: dict | None = None
            status_code = 200
            error: str | None = None
            try:
                async for chunk, chunk_usage in proxy.stream_sse(upstream_path, body):
                    if chunk_usage is not None:
                        usage = chunk_usage
                    if chunk:
                        if first_token and chunk.strip():
                            ttft_ms = (time.perf_counter() - start) * 1000.0
                            first_token = False
                        yield chunk
            except httpx.TimeoutException:
                status_code, error = 504, "upstream_timeout"
                yield _sse_error("Inference engine timed out.", "upstream_timeout")
            except httpx.HTTPError as exc:  # pragma: no cover - network dependent
                status_code, error = 502, "upstream_unavailable"
                logger.warning("stream upstream error", extra={"ctx_err": str(exc)})
                yield _sse_error("Inference engine unavailable.", "upstream_unavailable")
            finally:
                pt = int((usage or {}).get("prompt_tokens", 0) or 0)
                ct = int((usage or {}).get("completion_tokens", 0) or 0)
                tt = int((usage or {}).get("total_tokens", pt + ct) or 0)
                await limiter.release(key_id, tt or est, est)
                latency_ms = (time.perf_counter() - start) * 1000.0
                analytics.record(
                    request, status_code=status_code, latency_ms=latency_ms,
                    model=public_model, streamed=True,
                    prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
                    ttft_ms=ttft_ms, error=error,
                )

        headers = dict(_SSE_HEADERS)
        headers["x-request-id"] = getattr(request.state, "request_id", "")
        return StreamingResponse(event_stream(), headers=headers)

    # ---- non-streaming ----------------------------------------------------
    try:
        upstream = await proxy.forward_json(upstream_path, body)
    except httpx.TimeoutException:
        await limiter.release(key_id, est, est)
        analytics.record(
            request, status_code=504, latency_ms=(time.perf_counter() - start) * 1000.0,
            model=public_model, streamed=False, error="upstream_timeout",
        )
        return error_response(504, "Inference engine timed out.", err_type="api_error",
                              code="upstream_timeout")
    except httpx.HTTPError as exc:
        await limiter.release(key_id, est, est)
        analytics.record(
            request, status_code=502, latency_ms=(time.perf_counter() - start) * 1000.0,
            model=public_model, streamed=False, error="upstream_unavailable",
        )
        logger.warning("upstream error", extra={"ctx_err": str(exc)})
        return error_response(502, "Inference engine unavailable.", err_type="api_error",
                              code="upstream_unavailable")

    latency_ms = (time.perf_counter() - start) * 1000.0
    try:
        data = upstream.json()
    except json.JSONDecodeError:
        data = None

    usage = (data or {}).get("usage") if isinstance(data, dict) else None
    pt = int((usage or {}).get("prompt_tokens", 0) or 0)
    ct = int((usage or {}).get("completion_tokens", 0) or 0)
    tt = int((usage or {}).get("total_tokens", pt + ct) or 0)

    await limiter.release(key_id, tt or est, est)
    analytics.record(
        request, status_code=upstream.status_code, latency_ms=latency_ms,
        model=public_model, streamed=False,
        prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
        error=None if upstream.status_code < 400 else "upstream_error",
    )

    if data is None:
        # Pass through whatever the engine returned (already an error body).
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    return JSONResponse(status_code=upstream.status_code, content=data)


def _sse_error(message: str, code: str) -> bytes:
    payload = json.dumps(openai_error(message, err_type="api_error", code=code))
    return f"data: {payload}\n\ndata: [DONE]\n\n".encode("utf-8")
