"""Correlation and user context (HTTP headers + MCP tool args)."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request


@dataclass(frozen=True)
class UserContext:
    """Optional end-user identity forwarded to the LLM gateway via headers."""

    user_id: str
    user_roles: str
    user_groups: str
    user_teams: str


def _header(request: Request, name: str) -> str | None:
    """Return a stripped HTTP header value, or None if empty."""
    value = (request.headers.get(name) or "").strip()
    return value or None


def parse_http_correlation(request: Request) -> tuple[str, str, str | None]:
    """Read or generate request/session ids and optional trace id from HTTP headers."""
    rid = _header(request, "X-Request-Id") or str(uuid.uuid4())
    sid = _header(request, "X-Session-Id") or str(uuid.uuid4())
    tid = _header(request, "X-Trace-Id")
    return rid, sid, tid


def parse_http_user(request: Request) -> UserContext:
    """Build UserContext from X-User-* headers (defaults match gateway expectations)."""
    return UserContext(
        user_id=_header(request, "X-User-Id") or "-",
        user_roles=_header(request, "X-User-Roles") or "anyuser",
        user_groups=_header(request, "X-User-Groups") or "",
        user_teams=_header(request, "X-User-Teams") or "",
    )


def resolve_conversation_id(provided: str | None, *, use_env: bool = True) -> str:
    """Resolve conversation id from argument, env, or generate ``conv_<hex>``."""
    conv = (provided or "").strip()
    if not conv and use_env:
        conv = (os.environ.get("LLM_CONVERSATION_ID") or "").strip()
    return conv or f"conv_{uuid.uuid4().hex}"


def resolve_correlation(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    use_env_fallback: bool = True,
) -> tuple[str, str, str | None, str]:
    """Resolve correlation ids from tool args with optional env fallbacks."""
    rid = (request_id or "").strip()
    if not rid and use_env_fallback:
        rid = (os.environ.get("LLM_REQUEST_ID") or "").strip()
    rid = rid or str(uuid.uuid4())

    sid = (session_id or "").strip()
    if not sid and use_env_fallback:
        sid = (os.environ.get("LLM_SESSION_ID") or "").strip()
    sid = sid or str(uuid.uuid4())

    tid = (trace_id or "").strip()
    if not tid and use_env_fallback:
        tid = (os.environ.get("LLM_TRACE_ID") or "").strip()
    tid = tid or None

    conv = resolve_conversation_id(conversation_id, use_env=use_env_fallback)
    return rid, sid, tid, conv


def response_correlation_headers(
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None = None,
) -> dict[str, str]:
    """Response headers echoing correlation (and user id when present)."""
    headers = {
        "X-Request-Id": request_id,
        "X-Session-Id": session_id,
        "X-Conversation-Id": conversation_id,
    }
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    if user is not None:
        headers["X-User-Id"] = user.user_id
    return headers


def user_header_values(user: UserContext | None) -> dict[str, str]:
    """Map UserContext to outbound LLM gateway X-User-* headers."""
    if user is None:
        return {}
    out: dict[str, str] = {"X-User-Id": user.user_id}
    if user.user_roles:
        out["X-User-Roles"] = user.user_roles
    if user.user_groups:
        out["X-User-Groups"] = user.user_groups
    if user.user_teams:
        out["X-User-Teams"] = user.user_teams
    return out


def meta_event_payload(
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    *,
    repos: list[str] | None = None,
    repo: str | None = None,
    user: UserContext | None = None,
) -> dict[str, Any]:
    """First SSE ``meta`` event payload with correlation and optional repo/user fields."""
    data: dict[str, Any] = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
    }
    if repos is not None:
        data["repos"] = repos
    if repo is not None:
        data["repo"] = repo
    if user is not None:
        data["user_id"] = user.user_id
        data["user_roles"] = user.user_roles
        data["user_groups"] = user.user_groups
        data["user_teams"] = user.user_teams
    return data
