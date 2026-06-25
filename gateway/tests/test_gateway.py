"""End-to-end tests for the gateway against a mocked engine."""

from __future__ import annotations

AUTH = {"Authorization": "Bearer sk-test-key"}


def test_health_is_open(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/healthz").status_code == 200


def test_readyz_checks_upstream(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_models_requires_auth(client):
    assert client.get("/v1/models").status_code == 401
    r = client.get("/v1/models", headers=AUTH)
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert "qwen3.6-35b-a3b" in ids


def test_chat_rejects_missing_key(client):
    r = client.post("/v1/chat/completions", json={"model": "qwen3.6-35b-a3b",
                                                  "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_api_key"


def test_chat_rejects_bad_key(client):
    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer nope"},
        json={"model": "qwen3.6-35b-a3b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_chat_non_streaming(client):
    r = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "qwen3.6-35b-a3b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["usage"]["total_tokens"] == 15


def test_chat_unknown_model_404(client):
    r = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "does-not-exist", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


def test_chat_missing_messages_400(client):
    r = client.post("/v1/chat/completions", headers=AUTH, json={"model": "qwen3.6-35b-a3b"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "missing_messages"


def test_chat_streaming(client):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "qwen3.6-35b-a3b",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        text = "".join(chunk for chunk in r.iter_text())
    assert "delta" in text
    assert "[DONE]" in text


def test_model_alias_routes(client):
    # alias-model maps to the same upstream id and must be accepted.
    r = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "alias-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200


def test_rpm_rate_limit(client):
    payload = {"model": "qwen3.6-35b-a3b", "messages": [{"role": "user", "content": "hi"}]}
    # RPM is 5 (see conftest). The 6th request within the minute should 429.
    codes = [client.post("/v1/chat/completions", headers=AUTH, json=payload).status_code
             for _ in range(6)]
    assert codes.count(200) == 5
    assert codes[-1] == 429


def test_admin_requires_admin_key(client):
    assert client.get("/admin/config").status_code == 401
    r = client.get("/admin/config", headers={"Authorization": "Bearer admin-secret"})
    assert r.status_code == 200
    assert r.json()["default_model"] == "qwen3.6-35b-a3b"
