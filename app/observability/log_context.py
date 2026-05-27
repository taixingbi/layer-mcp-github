"""Bind logging context from correlation ids and emit structured extras."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.observability.correlation import UserContext
from app.observability.request_context import bind_http_context, bind_request_context


def latency_log_extra(latency: dict[str, int]) -> dict[str, Any]:
    """Map internal latency keys to JSON log field names (incl. duration_ms)."""
    extra: dict[str, Any] = {}
    mapping = {
        "github_readme": "latency_github_readme_ms",
        "github_search": "latency_github_search_ms",
        "chat": "latency_chat_ms",
        "follow_up_chat": "latency_follow_up_chat_ms",
        "total": "latency_total_ms",
    }
    for src, dst in mapping.items():
        if src in latency:
            extra[dst] = latency[src]
    if "total" in latency:
        extra["duration_ms"] = latency["total"]
    return extra


def user_log_extra(user: UserContext | None) -> dict[str, Any]:
    """Optional user_roles/groups/teams for structured logs."""
    if user is None:
        return {}
    return {
        "user_roles": user.user_roles,
        "user_groups": user.user_groups,
        "user_teams": user.user_teams,
    }


@contextmanager
def bind_ask_context(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None = None,
    method: str = "-",
    path: str = "-",
    status: str = "-",
):
    """Bind request + HTTP contextvars for the duration of one github_search call."""
    with bind_request_context(
        request_id,
        session_id,
        trace_id=trace_id,
        user_id=user.user_id if user else "-",
        conversation_id=conversation_id,
    ):
        with bind_http_context(method, path, status=status):
            yield
