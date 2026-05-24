"""Shared validation, logging, and LLM helpers for ask_repo (buffered + stream)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.allowlist import allowed_short_names
from app.allowlist.resolve import resolve_repos
from app.clients.github import github_token
from app.clients.llm import chat_completion, generate_follow_ups, llm_gateway_base
from app.observability.correlation import UserContext
from app.observability.log_context import latency_log_extra, user_log_extra
from app.observability.logging_config import logger

from .prompts import SYSTEM_PROMPT
from .response import build_tool_error


@dataclass(frozen=True)
class AskScope:
    """Resolved allowlist target(s) for one ask_repo invocation."""

    full_names: list[str]
    scope: str
    multi: bool

    @property
    def scope_label(self) -> str:
        return ", ".join(self.full_names)


def resolve_ask_scope(repo: str | None) -> tuple[AskScope | None, dict[str, Any] | None]:
    """Resolve repo argument; return ``(scope, None)`` or ``(None, error dict)``."""
    resolved = resolve_repos(repo)
    if not resolved.get("ok"):
        return None, resolved
    full_names: list[str] = resolved["full_names"]
    return (
        AskScope(full_names, str(resolved["scope"]), len(full_names) > 1),
        None,
    )


def resolve_ask_scope_or_error(repo: str | None) -> tuple[AskScope | None, str | None]:
    """Resolve scope and service prereqs; return ``(scope, None)`` or ``(None, error message)``."""
    scope, err = resolve_ask_scope(repo)
    if err is not None:
        return None, str(err.get("error") or "resolve failed")
    prereq = service_prereq_error()
    if prereq:
        return None, prereq
    return scope, None


def chat_messages(user_body: str) -> list[dict[str, str]]:
    """OpenAI-style messages for ask_repo chat (system + user with sources)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_body},
    ]


def service_prereq_error() -> str | None:
    """Return an error message when required env/services are missing, else ``None``."""
    if not github_token():
        return "GITHUB_TOKEN not set in .env"
    if not llm_gateway_base():
        return "LLM_GATEWAY_BASE_URL not set in .env (required to synthesize answers)"
    return None


def repo_log_extra(
    scope: AskScope,
    *,
    tool_name: str,
    stream: bool,
    user: UserContext | None,
) -> dict[str, Any]:
    """Structured log ``extra`` fields for repo scope and identity."""
    extra: dict[str, Any] = {
        "tool_name": tool_name,
        "stream": stream,
        "scope": scope.scope,
        "repo_count": len(scope.full_names),
        "repos": scope.full_names,
        **user_log_extra(user),
    }
    if len(scope.full_names) == 1:
        extra["repo"] = scope.full_names[0]
    return extra


def log_ask_fail(
    msg: str,
    *,
    tool_name: str,
    stream: bool,
    **extra: Any,
) -> None:
    """Emit a warning line for a failed ask (validation, env, or upstream)."""
    logger.warning(
        f"ask_repo{' stream' if stream else ''} fail {msg}",
        extra={"ok": False, "tool_name": tool_name, "stream": stream, "error_message": msg, **extra},
    )


def log_ask_start(scope: AskScope, *, tool_name: str, stream: bool, user: UserContext | None) -> None:
    """Log ask_repo / stream start with repo scope."""
    label = "ask_repo stream start" if stream else "ask_repo start"
    logger.info(
        f"{label} scope={scope.scope} repo_count={len(scope.full_names)}",
        extra=repo_log_extra(scope, tool_name=tool_name, stream=stream, user=user),
    )


def log_ask_github_done(
    citation_count: int,
    gh_latency: dict[str, int],
    *,
    stream: bool,
) -> None:
    """Log completion of README + code-search evidence gathering."""
    prefix = "ask_repo stream github_done" if stream else "ask_repo github_done"
    logger.info(
        f"{prefix} citation_count={citation_count}",
        extra={
            "phase": "github_done",
            "citation_count": citation_count,
            **latency_log_extra(gh_latency),
        },
    )


def log_ask_done(
    scope: AskScope,
    *,
    tool_name: str,
    stream: bool,
    user: UserContext | None,
    citation_count: int,
    follow_up_count: int,
    latency_ms: dict[str, int],
) -> None:
    """Log successful ask completion with latency breakdown."""
    prefix = "ask_repo stream done" if stream else "ask_repo done"
    logger.info(
        f"{prefix} citation_count={citation_count} follow_up_count={follow_up_count} "
        f"latency_total_ms={latency_ms.get('total', 0)}",
        extra={
            "ok": True,
            "citation_count": citation_count,
            "follow_up_count": follow_up_count,
            **repo_log_extra(scope, tool_name=tool_name, stream=stream, user=user),
            **latency_log_extra(latency_ms),
        },
    )


def log_ask_exception(exc: BaseException, *, stream: bool) -> None:
    """Log an upstream/transport exception with ``logger.exception``."""
    extra: dict[str, Any] = {"error_type": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        extra["upstream_status"] = exc.response.status_code
        msg = f"ask_repo{' stream' if stream else ''} upstream status={exc.response.status_code}"
    else:
        msg = f"ask_repo{' stream' if stream else ''} failed"
    logger.exception(msg, extra=extra)


def httpx_error_message(exc: BaseException) -> str:
    """Map httpx/ValueError exceptions to a client-facing error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"GitHub API error: {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return f"Request failed: {exc}"
    return str(exc)


def ms_elapsed(start: float) -> int:
    """Wall-clock milliseconds since ``time.perf_counter()`` start."""
    return int((time.perf_counter() - start) * 1000)


def run_buffered_llm(
    client: httpx.Client,
    *,
    question: str,
    user_body: str,
    scope_label: str,
    conversation_id: str,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    user: UserContext | None,
) -> tuple[str, list[str], dict[str, int], dict[str, int], dict[str, int]]:
    """Non-streaming chat + follow-ups; returns answer, follow-ups, latency slice, usages."""
    latency: dict[str, int] = {}
    messages = chat_messages(user_body)

    t0 = time.perf_counter()
    answer, chat_usage = chat_completion(
        client,
        messages=messages,
        conversation_id=conversation_id,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        user=user,
    )
    latency["chat"] = ms_elapsed(t0)

    t0 = time.perf_counter()
    follow_ups, follow_usage = generate_follow_ups(
        client,
        question,
        answer,
        scope_label,
        conversation_id=conversation_id,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        user=user,
    )
    latency["follow_up_chat"] = ms_elapsed(t0)
    return answer, follow_ups, latency, chat_usage, follow_usage


def tool_error_response(
    msg: str,
    repo: str | None,
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    tool_name: str = "ask_repo",
    user: UserContext | None = None,
) -> dict[str, Any]:
    """Standard failed tool response (``status.ok`` false)."""
    return build_tool_error(
        msg,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        user=user,
        repo=repo or None,
        allowed=allowed_short_names(),
    )
