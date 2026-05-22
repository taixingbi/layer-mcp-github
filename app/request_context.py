"""Request-scoped ids and HTTP metadata for log correlation (contextvars)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
_session_id_ctx: ContextVar[str] = ContextVar("session_id", default="-")
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")
_user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
_conversation_id_ctx: ContextVar[str] = ContextVar("conversation_id", default="-")
_http_method_ctx: ContextVar[str] = ContextVar("http_method", default="-")
_http_path_ctx: ContextVar[str] = ContextVar("http_path", default="-")
_http_status_ctx: ContextVar[str] = ContextVar("http_status", default="-")


def get_request_id() -> str:
    """Current request_id context value."""
    return _request_id_ctx.get()


def get_session_id() -> str:
    """Current session_id context value."""
    return _session_id_ctx.get()


def get_trace_id() -> str:
    """Current trace_id context value."""
    return _trace_id_ctx.get()


def get_user_id() -> str:
    """Current user_id context value."""
    return _user_id_ctx.get()


def get_conversation_id() -> str:
    """Current conversation_id context value."""
    return _conversation_id_ctx.get()


def get_http_method() -> str:
    """Current HTTP method for log lines."""
    return _http_method_ctx.get()


def get_http_path() -> str:
    """Current HTTP path for log lines."""
    return _http_path_ctx.get()


def get_http_status() -> str:
    """Current HTTP status string for log lines."""
    return _http_status_ctx.get()


@contextmanager
def bind_request_context(
    request_id: str,
    session_id: str,
    *,
    trace_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
):
    """Set correlation contextvars for nested log calls."""
    rid = (request_id or "").strip() or "-"
    sid = (session_id or "").strip() or "-"
    tid = (trace_id or "").strip() or "-"
    uid = (user_id or "").strip() or "-"
    cid = (conversation_id or "").strip() or "-"
    tokens = [
        _request_id_ctx.set(rid),
        _session_id_ctx.set(sid),
        _trace_id_ctx.set(tid),
        _user_id_ctx.set(uid),
        _conversation_id_ctx.set(cid),
    ]
    try:
        yield
    finally:
        _request_id_ctx.reset(tokens[0])
        _session_id_ctx.reset(tokens[1])
        _trace_id_ctx.reset(tokens[2])
        _user_id_ctx.reset(tokens[3])
        _conversation_id_ctx.reset(tokens[4])


@contextmanager
def bind_http_context(
    method: str,
    path: str,
    *,
    status: str = "-",
):
    """Set HTTP method/path/status contextvars for log formatting."""
    t_m = _http_method_ctx.set((method or "").strip() or "-")
    t_p = _http_path_ctx.set((path or "").strip() or "-")
    t_s = _http_status_ctx.set((status or "").strip() or "-")
    try:
        yield
    finally:
        _http_method_ctx.reset(t_m)
        _http_path_ctx.reset(t_p)
        _http_status_ctx.reset(t_s)
