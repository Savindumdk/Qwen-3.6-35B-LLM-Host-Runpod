"""Pytest fixtures: configure the gateway against a mocked upstream engine.

Tests never touch a real model. We set environment variables before importing
the app, clear the settings cache, and monkeypatch the proxy layer so the relay
pipeline (auth, routing, rate limiting, streaming, analytics) is exercised end
to end without a GPU.
"""

from __future__ import annotations

import os

import pytest

# Configure the gateway BEFORE importing app modules (Settings reads env once).
os.environ.update(
    {
        "GATEWAY_API_KEYS": "sk-test-key,sk-second-key",
        "ADMIN_API_KEY": "admin-secret",
        "DEFAULT_MODEL": "qwen3.6-35b-a3b",
        "MODEL_ALIASES": '{"qwen3.6-35b-a3b": "qwen3.6-35b-a3b", "alias-model": "qwen3.6-35b-a3b"}',
        "ANALYTICS_ENABLED": "false",
        "RATE_LIMIT_RPM": "5",
        "RATE_LIMIT_TPM": "0",
        "RATE_LIMIT_CONCURRENCY": "0",
        "UPSTREAM_BASE_URL": "http://127.0.0.1:9/v1",
        "LOG_JSON": "false",
    }
)

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import proxy
    from app.main import app

    # ---- mocked upstream -------------------------------------------------
    class FakeResp:
        def __init__(self, status=200, payload=None):
            self.status_code = status
            self._payload = payload or {}
            self.content = b"{}"
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._payload

    async def fake_forward_json(path, body):
        return FakeResp(
            200,
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    async def fake_stream_sse(path, body, settings=None):
        frames = [
            'data: {"id":"c","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hel"}}]}',
            'data: {"id":"c","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"lo"}}]}',
            'data: {"id":"c","choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
            "data: [DONE]",
        ]
        for f in frames:
            yield (f + "\n").encode(), None
        yield b"", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    async def fake_health():
        return True

    monkeypatch.setattr(proxy, "forward_json", fake_forward_json)
    monkeypatch.setattr(proxy, "stream_sse", fake_stream_sse)
    monkeypatch.setattr(proxy, "check_upstream_health", fake_health)

    with TestClient(app) as c:
        yield c


AUTH = {"Authorization": "Bearer sk-test-key"}
