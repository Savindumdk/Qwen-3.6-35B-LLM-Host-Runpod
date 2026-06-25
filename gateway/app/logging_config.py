"""Structured logging setup.

Production observability starts with machine-parseable logs. We emit one JSON
object per line so the output drops straight into Loki/Elastic/CloudWatch, while
still being readable in a terminal. A request-id ``ContextVar`` threads a trace
id through every log line emitted while handling a single request.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Populated by RequestContextMiddleware; read by the log formatter.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
api_key_id_ctx: ContextVar[str | None] = ContextVar("api_key_id", default=None)


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        kid = api_key_id_ctx.get()
        if kid:
            payload["api_key_id"] = kid
        # Merge structured extras passed via ``logger.info(..., extra={"x": 1})``.
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_ctx.get()
        prefix = f"[{rid}] " if rid else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {prefix}{record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Install our formatter on the root logger and tame noisy libraries."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn duplicates access logs; route everything through our handler and
    # silence the redundant access logger (we log requests ourselves).
    for noisy in ("uvicorn", "uvicorn.error"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx/httpcore are chatty at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
