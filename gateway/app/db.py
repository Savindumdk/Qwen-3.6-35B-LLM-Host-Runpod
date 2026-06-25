"""Async persistence layer for usage analytics and request history.

We use SQLAlchemy's async engine over SQLite by default (zero-ops, single file)
but the same code runs unchanged against Postgres simply by pointing
``DATABASE_URL`` at ``postgresql+asyncpg://...``. Writes happen on a background
task so request latency is never coupled to disk I/O.
"""

from __future__ import annotations

import datetime as dt
from typing import AsyncIterator

from sqlalchemy import (
    Float,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import get_settings
from .logging_config import get_logger

logger = get_logger("gateway.db")

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class RequestLog(Base):
    """One row per completed (or failed) inference request."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, index=True)

    api_key_id: Mapped[str | None] = mapped_column(String(32), index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))

    endpoint: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(128), index=True)
    streamed: Mapped[bool] = mapped_column(default=False)

    status_code: Mapped[int] = mapped_column(Integer, index=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    ttft_ms: Mapped[float | None] = mapped_column(Float)  # time-to-first-token

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    error: Mapped[str | None] = mapped_column(Text)
    # Optional full payloads (only stored when ANALYTICS_REDACT_CONTENT=false).
    request_preview: Mapped[str | None] = mapped_column(Text)
    response_preview: Mapped[str | None] = mapped_column(Text)


async def init_db() -> None:
    """Create the engine, session factory and tables (idempotent)."""
    global _engine, _sessionmaker
    settings = get_settings()
    if not settings.analytics_enabled:
        logger.info("analytics disabled; skipping db init")
        return

    # Ensure the parent directory exists for file-based SQLite URLs.
    url = settings.database_url
    if url.startswith("sqlite") and ":///" in url:
        import os

        path = url.split(":///", 1)[1]
        if path and path not in (":memory:",):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    _engine = create_async_engine(url, future=True, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("analytics db ready", extra={"ctx_database_url": url})


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session (admin endpoints)."""
    if _sessionmaker is None:
        raise RuntimeError("database not initialised")
    async with _sessionmaker() as session:
        yield session


async def record_request(entry: dict) -> None:
    """Persist a single :class:`RequestLog`. Safe to call as a background task.

    Never raises into the caller: analytics must not break inference.
    """
    if _sessionmaker is None:
        return
    try:
        async with _sessionmaker() as session:
            session.add(RequestLog(**entry))
            await session.commit()
    except Exception:  # pragma: no cover - defensive
        logger.exception("failed to persist request log")


# --------------------------------------------------------------- aggregations
async def usage_summary(session: AsyncSession, since: dt.datetime | None = None):
    """Return aggregate token/request counts grouped by api key and model."""
    q = select(
        RequestLog.api_key_id,
        RequestLog.model,
        func.count().label("requests"),
        func.sum(RequestLog.prompt_tokens).label("prompt_tokens"),
        func.sum(RequestLog.completion_tokens).label("completion_tokens"),
        func.sum(RequestLog.total_tokens).label("total_tokens"),
        func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
    ).group_by(RequestLog.api_key_id, RequestLog.model)
    if since is not None:
        q = q.where(RequestLog.created_at >= since)
    rows = (await session.execute(q)).all()
    return [
        {
            "api_key_id": r.api_key_id,
            "model": r.model,
            "requests": r.requests,
            "prompt_tokens": int(r.prompt_tokens or 0),
            "completion_tokens": int(r.completion_tokens or 0),
            "total_tokens": int(r.total_tokens or 0),
            "avg_latency_ms": round(float(r.avg_latency_ms or 0), 2),
        }
        for r in rows
    ]
