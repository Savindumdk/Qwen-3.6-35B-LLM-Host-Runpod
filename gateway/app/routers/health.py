"""Liveness and readiness probes.

* ``/health`` and ``/healthz`` are **liveness** — they answer 200 as soon as the
  gateway process is up, regardless of the engine. Use these for the container
  HEALTHCHECK / RunPod restarts of the gateway itself.
* ``/readyz`` is **readiness** — it returns 200 only when the upstream inference
  engine is reachable, so a load balancer won't route traffic before the model
  has finished loading (a 35B model can take a minute or two to warm up).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import proxy
from ..config import get_settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    s = get_settings()
    return {
        "service": s.service_name,
        "status": "ok",
        "docs": "/docs",
        "openai_base": "/v1",
    }


@router.get("/health")
@router.get("/healthz")
async def health():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    ok = await proxy.check_upstream_health()
    if ok:
        return {"status": "ready"}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "reason": "upstream_engine_unavailable"},
    )
