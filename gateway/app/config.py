"""Central configuration for the gateway.

All runtime configuration is read from environment variables (or a local
``.env`` file) through ``pydantic-settings``. Keeping every tunable in one typed
object means the rest of the codebase never reaches for ``os.environ`` directly,
which makes the configuration surface easy to document, validate and test.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Field names map to upper-cased environment variables, e.g. ``GATEWAY_PORT``
    populates :attr:`gateway_port`. Defaults are chosen so the stack runs locally
    with zero configuration, while every production-relevant knob is overridable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ server
    gateway_host: str = Field(default="0.0.0.0", alias="GATEWAY_HOST")
    gateway_port: int = Field(default=8000, alias="GATEWAY_PORT")
    workers: int = Field(default=1, alias="GATEWAY_WORKERS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")
    environment: str = Field(default="production", alias="ENVIRONMENT")
    # Public name advertised in logs / OpenAI ``system_fingerprint``.
    service_name: str = Field(default="qwen-gateway", alias="SERVICE_NAME")

    # -------------------------------------------------------------- upstream(s)
    # Base URL of the OpenAI-compatible inference engine (vLLM or llama.cpp).
    # MUST include the ``/v1`` suffix, e.g. ``http://engine:8001/v1``.
    upstream_base_url: str = Field(
        default="http://127.0.0.1:8001/v1", alias="UPSTREAM_BASE_URL"
    )
    # Optional bearer token the gateway presents to the upstream engine.
    upstream_api_key: str | None = Field(default=None, alias="UPSTREAM_API_KEY")
    # Seconds to wait for the upstream to *start* responding. Generation can take
    # much longer; the streaming read timeout is governed separately below.
    upstream_connect_timeout: float = Field(
        default=10.0, alias="UPSTREAM_CONNECT_TIMEOUT"
    )
    # Total read timeout for non-streaming requests; for streaming we keep the
    # socket open as long as chunks keep arriving (see proxy.py).
    request_timeout: float = Field(default=600.0, alias="REQUEST_TIMEOUT_SECONDS")
    # Idle timeout between streamed chunks before we give up on a hung upstream.
    stream_idle_timeout: float = Field(default=120.0, alias="STREAM_IDLE_TIMEOUT")
    # Size of the shared httpx connection pool.
    upstream_max_connections: int = Field(
        default=100, alias="UPSTREAM_MAX_CONNECTIONS"
    )

    # ----------------------------------------------------------------- routing
    # Comma-separated list of model ids clients are allowed to request, OR a JSON
    # object mapping public model id -> upstream model id (for aliasing).
    # Example list:  "qwen3.6-35b-a3b"
    # Example map:   '{"qwen3.6-35b-a3b": "Qwen3.6-35B-A3B", "fast": "Qwen3.6-35B-A3B"}'
    model_aliases_raw: str = Field(default="", alias="MODEL_ALIASES")
    # Default model id served when a request omits ``model`` (some tools do).
    default_model: str = Field(default="qwen3.6-35b-a3b", alias="DEFAULT_MODEL")
    # When true, the gateway proxies any model name through to the upstream
    # instead of rejecting unknown ids (useful while iterating on models).
    allow_unlisted_models: bool = Field(
        default=False, alias="ALLOW_UNLISTED_MODELS"
    )

    # -------------------------------------------------------------------- auth
    # Comma-separated client API keys accepted in the ``Authorization`` header.
    # These are the keys you paste into Zoo Code. Generate with ``openssl rand``.
    api_keys_raw: str = Field(default="", alias="GATEWAY_API_KEYS")
    # Separate key that unlocks the /admin/* analytics endpoints.
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    # When true (default) the gateway refuses to start without any API key set,
    # preventing an accidentally open endpoint. Set false only for local dev.
    require_auth: bool = Field(default=True, alias="REQUIRE_AUTH")

    # ------------------------------------------------------------- rate limits
    # Per-key limits. 0 disables the respective limit.
    rate_limit_rpm: int = Field(default=120, alias="RATE_LIMIT_RPM")
    rate_limit_tpm: int = Field(default=200_000, alias="RATE_LIMIT_TPM")
    rate_limit_concurrency: int = Field(default=8, alias="RATE_LIMIT_CONCURRENCY")

    # --------------------------------------------------------------- analytics
    analytics_enabled: bool = Field(default=True, alias="ANALYTICS_ENABLED")
    # SQLAlchemy async URL. Defaults to a SQLite file under ./data.
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/gateway.db", alias="DATABASE_URL"
    )
    # When true, the prompt/response text is NOT stored — only token counts and
    # metadata. Keep true unless you explicitly need full request history.
    analytics_redact_content: bool = Field(
        default=True, alias="ANALYTICS_REDACT_CONTENT"
    )
    # Inject ``stream_options.include_usage`` so streamed responses carry token
    # usage for analytics. Harmless for OpenAI-compatible clients (extra final
    # chunk with empty choices), but can be disabled if a client misbehaves.
    capture_stream_usage: bool = Field(default=True, alias="CAPTURE_STREAM_USAGE")

    # --------------------------------------------------------------------- cors
    cors_origins_raw: str = Field(default="*", alias="CORS_ORIGINS")

    # --------------------------------------------------------------- hardening
    # Reject request bodies larger than this many bytes (defends the proxy).
    max_request_bytes: int = Field(default=20 * 1024 * 1024, alias="MAX_REQUEST_BYTES")

    # ------------------------------------------------------------- validators -
    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    # ---------------------------------------------------------- derived views -
    @property
    def api_keys(self) -> set[str]:
        return {k.strip() for k in self.api_keys_raw.split(",") if k.strip()}

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw.strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def model_map(self) -> dict[str, str]:
        """Public model id -> upstream model id.

        Accepts either a JSON object or a comma-separated list (where each entry
        maps to itself). Always includes :attr:`default_model`.
        """
        raw = self.model_aliases_raw.strip()
        mapping: dict[str, str] = {}
        if raw.startswith("{"):
            try:
                obj: dict[str, Any] = json.loads(raw)
                mapping = {str(k): str(v) for k, v in obj.items()}
            except json.JSONDecodeError:
                mapping = {}
        elif raw:
            mapping = {m.strip(): m.strip() for m in raw.split(",") if m.strip()}
        # Guarantee the default model is always routable.
        mapping.setdefault(self.default_model, self.default_model)
        return mapping

    def resolve_model(self, requested: str | None) -> str | None:
        """Map a client-requested model id to the upstream id, or ``None``."""
        if not requested:
            return self.model_map.get(self.default_model)
        if requested in self.model_map:
            return self.model_map[requested]
        if self.allow_unlisted_models:
            return requested
        return None


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
