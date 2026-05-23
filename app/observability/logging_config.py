"""Stderr JSON logging for ``layer_mcp.github``."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import ROOT
from app.observability.request_context import (
    get_conversation_id,
    get_http_method,
    get_http_path,
    get_http_status,
    get_request_id,
    get_session_id,
    get_trace_id,
    get_user_id,
)

logger = logging.getLogger("layer_mcp.github")

_LOG_TZ = ZoneInfo(os.environ.get("LOG_TZ", "America/New_York"))

_EXTRA_JSON_FIELDS = (
    "duration_ms",
    "latency_total_ms",
    "latency_github_readme_ms",
    "latency_github_search_ms",
    "latency_chat_ms",
    "latency_follow_up_chat_ms",
    "repo",
    "repos",
    "repo_count",
    "scope",
    "stream",
    "tool_name",
    "phase",
    "citation_count",
    "follow_up_count",
    "ok",
    "reason",
    "upstream_status",
    "error_type",
    "error_message",
    "user_roles",
    "user_groups",
    "user_teams",
)


class _RequestContextFilter(logging.Filter):
    """Attach contextvars and record extras to each LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = get_request_id()
        record.request_id = "-" if rid == "-" else rid
        record.session_id = "-" if rid == "-" else get_session_id()
        tid = get_trace_id()
        record.trace_id = tid if tid != "-" else "-"
        uid = get_user_id()
        record.user_id = uid if uid else "-"
        conv = get_conversation_id()
        record.conversation_id = conv if conv else "-"
        record.method = get_http_method()
        record.path = get_http_path()
        ctx_status = get_http_status()
        if ctx_status != "-":
            record.status = ctx_status
        elif not hasattr(record, "status"):
            record.status = "-"
        return True


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line (layer-rag-query shape)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=_LOG_TZ).isoformat(),
            "level": record.levelname,
            "request_id": getattr(record, "request_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
            "method": getattr(record, "method", "-"),
            "path": getattr(record, "path", "-"),
            "status": getattr(record, "status", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        for key in _EXTRA_JSON_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Configure stderr JSON logging and quiet httpx/httpcore loggers."""
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    logger.setLevel(level)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False
    logger.addFilter(_RequestContextFilter())

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(level)
    stderr.setFormatter(_JsonFormatter())
    logger.addHandler(stderr)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger.info("logging configured (stderr JSON)", extra={"backend": str(ROOT)})
