"""Async reverse-proxy to the OpenAI-compatible inference engine.

A single shared :class:`httpx.AsyncClient` (created on startup, closed on
shutdown) carries every upstream call so connection pooling and HTTP/1.1
keep-alive are reused across requests. The proxy is deliberately thin: it
forwards bodies the engine already understands and streams Server-Sent Events
byte-for-byte, so any feature vLLM/llama.cpp add (logprobs, tool calls,
reasoning_content) flows through without gateway changes.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .config import Settings, get_settings
from .logging_config import get_logger

logger = get_logger("gateway.proxy")

_client: httpx.AsyncClient | None = None
# Full upstream base, e.g. "http://engine:8001/v1" (no trailing slash). We build
# absolute URLs from this rather than relying on httpx base_url joining, which
# follows RFC 3986 and would silently drop the "/v1" segment for "/path" inputs.
_base_url: str = ""


def init_client() -> None:
    """Create the shared client. Called from the app lifespan."""
    global _client, _base_url
    s = get_settings()
    _base_url = s.upstream_base_url.rstrip("/")
    limits = httpx.Limits(
        max_connections=s.upstream_max_connections,
        max_keepalive_connections=s.upstream_max_connections,
    )
    # connect timeout bounded; read/write left generous because generation of a
    # long completion legitimately keeps the socket busy for minutes.
    timeout = httpx.Timeout(
        connect=s.upstream_connect_timeout,
        read=s.request_timeout,
        write=s.request_timeout,
        pool=s.upstream_connect_timeout,
    )
    headers = {}
    if s.upstream_api_key:
        headers["Authorization"] = f"Bearer {s.upstream_api_key}"
    _client = httpx.AsyncClient(limits=limits, timeout=timeout, headers=headers)
    logger.info("upstream client ready", extra={"ctx_upstream": _base_url})


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("proxy client not initialised")
    return _client


# --------------------------------------------------------------------- helpers
def estimate_tokens(body: dict) -> int:
    """Cheap, dependency-free prompt-token estimate for admission control.

    We deliberately avoid importing the model tokenizer (heavy, and the gateway
    is model-agnostic). A ~4 chars/token heuristic is plenty for rate limiting,
    and TPM is reconciled with the engine's exact ``usage`` once the response
    completes (see rate_limit.reconcile).
    """
    text_len = 0
    for msg in body.get("messages", []) or []:
        content = msg.get("content")
        if isinstance(content, str):
            text_len += len(content)
        elif isinstance(content, list):  # multimodal content parts
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_len += len(part["text"])
    if isinstance(body.get("prompt"), str):
        text_len += len(body["prompt"])
    # Add the requested max output so TPM accounts for generation too.
    max_out = body.get("max_tokens") or body.get("max_completion_tokens") or 0
    return max(1, text_len // 4 + int(max_out or 0))


# ------------------------------------------------------------- non-streaming -
async def forward_json(path: str, body: dict) -> httpx.Response:
    """POST a JSON body and return the full (non-streaming) response."""
    client = get_client()
    return await client.post(_base_url + path, json=body)


async def get_upstream(path: str) -> httpx.Response:
    client = get_client()
    return await client.get(_base_url + path)


# ----------------------------------------------------------------- streaming -
async def stream_sse(
    path: str, body: dict, settings: Settings | None = None
) -> AsyncIterator[tuple[bytes, dict | None]]:
    """Proxy a streaming chat/completion.

    Yields ``(raw_chunk_bytes, usage_or_none)``. ``usage`` is non-None only on
    the terminal chunk that carries token accounting (when the upstream honours
    ``stream_options.include_usage``). The router relays the raw bytes to the
    client and uses the parsed usage for analytics + rate-limit reconciliation.
    """
    settings = settings or get_settings()
    client = get_client()
    last_usage: dict | None = None

    async with client.stream("POST", _base_url + path, json=body) as resp:
        if resp.status_code >= 400:
            # Surface an upstream error as a proper SSE frame so streaming
            # clients (which only parse `data:` events) see a clean error rather
            # than a raw JSON blob mid-stream. Compact to a SINGLE line first:
            # SSE events are newline-delimited, so a pretty-printed multi-line
            # error body would otherwise break frame boundaries.
            raw = (await resp.aread()).decode("utf-8", "replace").strip()
            try:
                compact = json.dumps(json.loads(raw))
            except (json.JSONDecodeError, ValueError):
                compact = json.dumps(
                    {"error": {"message": raw or "upstream error",
                               "type": "api_error", "code": "upstream_error"}}
                )
            yield f"data: {compact}\n\n".encode("utf-8"), None
            yield b"data: [DONE]\n\n", None
            return
        async for line in resp.aiter_lines():
            if not line:
                # Preserve SSE frame boundaries (blank line between events).
                yield b"\n", None
                continue
            # Sniff usage out of ``data:`` frames without disturbing pass-through.
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload and payload != "[DONE]":
                    try:
                        obj = json.loads(payload)
                        if isinstance(obj, dict) and obj.get("usage"):
                            last_usage = obj["usage"]
                    except json.JSONDecodeError:
                        pass
            yield (line + "\n").encode("utf-8"), None

    # Emit one final sentinel so the router can record usage after the stream.
    yield b"", last_usage


# -------------------------------------------------------------- health probe -
async def check_upstream_health() -> bool:
    """Return True if the engine answers on its /health (or /models) endpoint."""
    client = get_client()
    # vLLM and llama.cpp both expose /health at the SERVER root (one level above
    # /v1). Derive it from the configured base url.
    root = _base_url.rsplit("/v1", 1)[0] if "/v1" in _base_url else _base_url
    for url in (f"{root}/health", f"{_base_url}/models"):
        try:
            r = await client.get(url, timeout=5.0)
            if r.status_code < 500:
                return True
        except httpx.HTTPError:
            continue
    return False
