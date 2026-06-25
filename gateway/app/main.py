"""FastAPI application factory and entrypoint.

Wires together configuration, logging, the analytics DB, the upstream proxy
client and the rate limiter under a single lifespan, mounts the OpenAI-compatible
routers, and installs cross-cutting middleware. Import path for servers:
``app.main:app``.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, proxy
from .config import get_settings
from .errors import openai_error
from .logging_config import configure_logging, get_logger
from .middleware import RequestContextMiddleware
from .rate_limit import RateLimiter
from .routers import admin, chat, completions, embeddings, health, models

logger = get_logger("gateway.main")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)

    # Fail fast rather than expose an unauthenticated inference endpoint.
    if s.require_auth and not s.api_keys:
        raise RuntimeError(
            "No GATEWAY_API_KEYS configured but REQUIRE_AUTH=true. Set at least "
            "one client API key, or set REQUIRE_AUTH=false for local dev only."
        )

    logger.info(
        "starting gateway",
        extra={
            "ctx_service": s.service_name,
            "ctx_environment": s.environment,
            "ctx_upstream": s.upstream_base_url,
            "ctx_models": sorted(s.model_map.keys()),
        },
    )

    await db.init_db()
    proxy.init_client()
    app.state.limiter = RateLimiter()
    try:
        yield
    finally:
        await proxy.close_client()
        await db.close_db()
        logger.info("gateway stopped")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Qwen OpenAI-Compatible Gateway",
        version="1.0.0",
        description=(
            "Production OpenAI-compatible gateway in front of a self-hosted "
            "vLLM / llama.cpp engine. Provides auth, rate limiting, usage "
            "analytics, logging, model routing and health checks."
        ),
        lifespan=lifespan,
    )

    # CORS (browsers / web tooling). Auth is via the Authorization bearer header,
    # NOT cookies, so we keep allow_credentials=False — that lets us safely return
    # a wildcard `Access-Control-Allow-Origin: *` without the credentialed-
    # wildcard antipattern (a wildcard ACAO with credentials is rejected by
    # browsers anyway and weakens CSRF posture for cookie auth).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    # Routers — order is cosmetic; paths are distinct.
    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(chat.router)
    app.include_router(completions.router)
    app.include_router(embeddings.router)
    app.include_router(admin.router)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        # Our handlers raise HTTPException with an already-formed OpenAI error
        # envelope in ``detail``; pass it through unwrapped instead of letting
        # FastAPI nest it under {"detail": ...}.
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = openai_error(
                detail if isinstance(detail, str) else "Request failed.",
                err_type="invalid_request_error",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=openai_error(
                "Invalid request: " + "; ".join(
                    e.get("msg", "invalid") for e in exc.errors()[:3]
                ),
                err_type="invalid_request_error",
                code="invalid_request",
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content=openai_error(
                "Internal gateway error.", err_type="api_error",
                code="internal_error",
            ),
        )

    return app


app = create_app()
