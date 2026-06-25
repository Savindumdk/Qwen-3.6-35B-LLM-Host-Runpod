"""Analytics recording for inference endpoints.

Route handlers call :func:`record` at the precise moment a request finishes —
after a non-streaming response is built, or after the final chunk of a stream —
so token usage and end-to-end latency are accurate. Persistence is fire-and-
forget: a failure to write analytics never affects the client response.
"""

from __future__ import annotations

import asyncio

from starlette.requests import Request

from . import db
from .config import get_settings

# asyncio does not keep a strong reference to bare tasks, so a fire-and-forget
# task can be garbage-collected before it runs. Hold references until they
# complete to guarantee analytics writes are not dropped under load.
_pending: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def record(
    request: Request,
    *,
    status_code: int,
    latency_ms: float,
    model: str | None,
    streamed: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    ttft_ms: float | None = None,
    error: str | None = None,
    request_preview: str | None = None,
    response_preview: str | None = None,
) -> None:
    """Build and asynchronously persist one :class:`db.RequestLog` row."""
    s = get_settings()
    if not s.analytics_enabled:
        return

    if s.analytics_redact_content:
        request_preview = None
        response_preview = None

    entry = {
        "request_id": getattr(request.state, "request_id", ""),
        "api_key_id": getattr(request.state, "api_key_id", None),
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "endpoint": request.url.path,
        "model": model,
        "streamed": streamed,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(total_tokens or (prompt_tokens + completion_tokens) or 0),
        "error": error,
        "request_preview": request_preview,
        "response_preview": response_preview,
    }
    _spawn(db.record_request(entry))
