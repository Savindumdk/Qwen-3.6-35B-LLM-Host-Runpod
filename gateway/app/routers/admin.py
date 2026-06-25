"""``/admin/*`` — operational analytics, guarded by ``ADMIN_API_KEY``.

These endpoints expose the usage data the gateway records: aggregate token spend
per key/model, recent request history, and a config snapshot. They are separate
from the OpenAI surface so you can safely expose ``/v1`` to clients while keeping
analytics behind a distinct admin credential.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import proxy
from ..auth import require_admin
from ..config import get_settings
from ..db import RequestLog, get_session, usage_summary

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _since(hours: int | None) -> dt.datetime | None:
    if not hours:
        return None
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


@router.get("/usage")
async def usage(
    hours: int | None = Query(default=24, ge=0, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    """Token + request totals grouped by api key and model."""
    rows = await usage_summary(session, since=_since(hours))
    return {"window_hours": hours, "by_key_model": rows}


@router.get("/stats")
async def stats(
    hours: int | None = Query(default=24, ge=0, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    """Headline counters for the selected time window."""
    since = _since(hours)
    q = select(
        func.count().label("requests"),
        func.coalesce(func.sum(RequestLog.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
        func.coalesce(func.avg(RequestLog.latency_ms), 0).label("avg_latency_ms"),
        func.coalesce(func.avg(RequestLog.ttft_ms), 0).label("avg_ttft_ms"),
    )
    errs = select(func.count()).where(RequestLog.status_code >= 400)
    if since is not None:
        q = q.where(RequestLog.created_at >= since)
        errs = errs.where(RequestLog.created_at >= since)
    row = (await session.execute(q)).one()
    error_count = (await session.execute(errs)).scalar() or 0
    return {
        "window_hours": hours,
        "requests": row.requests,
        "errors": int(error_count),
        "prompt_tokens": int(row.prompt_tokens),
        "completion_tokens": int(row.completion_tokens),
        "total_tokens": int(row.total_tokens),
        "avg_latency_ms": round(float(row.avg_latency_ms), 2),
        "avg_ttft_ms": round(float(row.avg_ttft_ms), 2),
    }


@router.get("/requests")
async def recent_requests(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Most recent request-history rows (newest first)."""
    q = (
        select(RequestLog)
        .order_by(desc(RequestLog.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "request_id": r.request_id,
                "created_at": r.created_at.isoformat(),
                "api_key_id": r.api_key_id,
                "endpoint": r.endpoint,
                "model": r.model,
                "streamed": r.streamed,
                "status_code": r.status_code,
                "latency_ms": r.latency_ms,
                "ttft_ms": r.ttft_ms,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "error": r.error,
            }
            for r in rows
        ],
    }


@router.get("/config")
async def config_snapshot():
    """Non-secret view of the running configuration (useful for debugging)."""
    s = get_settings()
    upstream_ok = await proxy.check_upstream_health()
    return {
        "service_name": s.service_name,
        "environment": s.environment,
        "upstream_base_url": s.upstream_base_url,
        "upstream_healthy": upstream_ok,
        "default_model": s.default_model,
        "models": sorted(s.model_map.keys()),
        "allow_unlisted_models": s.allow_unlisted_models,
        "rate_limit_rpm": s.rate_limit_rpm,
        "rate_limit_tpm": s.rate_limit_tpm,
        "rate_limit_concurrency": s.rate_limit_concurrency,
        "analytics_enabled": s.analytics_enabled,
        "num_api_keys": len(s.api_keys),
    }
