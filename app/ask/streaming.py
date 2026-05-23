"""SSE streaming and MCP stream consumer."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from mcp.server.fastmcp import Context

from app.clients.llm import generate_follow_ups, iter_chat_completion_stream
from app.observability.correlation import UserContext, meta_event_payload, resolve_correlation
from app.observability.log_context import bind_ask_context

from .common import (
    chat_messages,
    error_payload,
    httpx_error_message,
    log_ask_done,
    log_ask_exception,
    log_ask_fail,
    log_ask_github_done,
    log_ask_start,
    resolve_ask_scope_or_error,
)
from .pipeline import finish_ask_repo_result, gather_github_evidence
from .sse import parse_sse_frame, sse_format


async def stream_ask_repo_events(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    user: UserContext | None = None,
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str, dict[str, Any]], None] | None = None,
    http_method: str = "-",
    http_path: str = "-",
    tool_name: str = "ask_repo",
) -> AsyncIterator[str]:
    """Yield SSE frames for ask_repo: meta, status, answer_delta, done, or error."""
    rid, sid, tid, conv = resolve_correlation(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id_arg,
    )

    async def _emit_error(msg: str) -> AsyncIterator[str]:
        log_ask_fail(msg, tool_name=tool_name, stream=True)
        yield sse_format("error", error_payload(msg, repo, request_id=rid, session_id=sid, trace_id=tid, conversation_id=conv))

    with bind_ask_context(
        request_id=rid,
        session_id=sid,
        trace_id=tid,
        conversation_id=conv,
        user=user,
        method=http_method,
        path=http_path,
    ):
        scope, err_msg = resolve_ask_scope_or_error(repo)
        if err_msg is not None:
            async for frame in _emit_error(err_msg):
                yield frame
            return

        assert scope is not None
        log_ask_start(scope, tool_name=tool_name, stream=True, user=user)

        yield sse_format(
            "meta",
            meta_event_payload(
                rid,
                sid,
                tid,
                conv,
                repos=scope.full_names,
                repo=scope.full_names[0] if len(scope.full_names) == 1 else None,
                user=user,
            ),
        )

        t0 = time.perf_counter()
        latency: dict[str, int] = {}
        chat_usage: dict[str, int] = {}
        follow_usage: dict[str, int] = {}
        citations: list[dict[str, Any]] = []
        answer = ""
        follow_ups: list[str] = []

        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as client:
                yield sse_format("status", {"phase": "github_readme", "repos": scope.full_names})
                if on_status:
                    on_status("github_readme", {"repos": scope.full_names})

                citations, user_body, gh_latency = gather_github_evidence(
                    client, scope.full_names, question, scope.multi
                )
                latency.update(gh_latency)
                log_ask_github_done(len(citations), gh_latency, stream=True)
                yield sse_format(
                    "status",
                    {
                        "phase": "github_done",
                        "latency_ms": gh_latency,
                        "citation_count": len(citations),
                    },
                )

                yield sse_format("status", {"phase": "chat_stream"})
                t_llm = time.perf_counter()
                for kind, payload in iter_chat_completion_stream(
                    client,
                    messages=chat_messages(user_body),
                    conversation_id=conv,
                    request_id=rid,
                    session_id=sid,
                    trace_id=tid,
                    user=user,
                ):
                    if kind == "delta":
                        text = str(payload)
                        if on_token:
                            on_token(text)
                        yield sse_format("answer_delta", {"text": text})
                    elif kind == "usage":
                        chat_usage = payload
                    elif kind == "done":
                        answer = str(payload)

                latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

                yield sse_format("status", {"phase": "follow_up_chat"})
                t_llm = time.perf_counter()
                follow_ups, follow_usage = generate_follow_ups(
                    client,
                    question,
                    answer,
                    scope.scope_label,
                    conversation_id=conv,
                    request_id=rid,
                    session_id=sid,
                    trace_id=tid,
                    user=user,
                )
                latency["follow_up_chat"] = int((time.perf_counter() - t_llm) * 1000)

        except (httpx.HTTPError, ValueError) as e:
            log_ask_exception(e, stream=True)
            yield sse_format("error", {"ok": False, "error": httpx_error_message(e)})
            return

        result = finish_ask_repo_result(
            full_names=scope.full_names,
            citations=citations,
            answer=answer,
            follow_ups=follow_ups,
            latency=latency,
            chat_usage=chat_usage,
            follow_usage=follow_usage,
            rid=rid,
            sid=sid,
            tid=tid,
            conv=conv,
            t0=t0,
        )
        log_ask_done(
            scope,
            tool_name=tool_name,
            stream=True,
            user=user,
            citation_count=len(citations),
            follow_up_count=len(follow_ups),
            latency_ms=result["latency_ms"],
        )
        yield sse_format("done", result)


async def ask_repo_mcp_stream(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    ctx: Context | None = None,
    http_method: str = "-",
    http_path: str = "stdio",
    tool_name: str = "ask_repo",
) -> dict[str, Any]:
    """Consume ``stream_ask_repo_events`` and map frames to MCP progress/logs; return final result."""
    final: dict[str, Any] = {"ok": False, "error": "stream ended without result"}
    step = 0
    total_steps = 6

    async for frame in stream_ask_repo_events(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id_arg=conversation_id_arg,
        http_method=http_method,
        http_path=http_path,
        tool_name=tool_name,
    ):
        event, data = parse_sse_frame(frame)

        if ctx:
            if event == "status":
                step += 1
                await ctx.report_progress(step, total_steps, data.get("phase", ""))
            elif event == "answer_delta":
                text = data.get("text") or ""
                if text:
                    await ctx.info(json.dumps({"type": "answer_delta", "text": text}))
            elif event == "error":
                await ctx.error(data.get("error", "stream error"))
                return data

        if event == "done":
            final = data
        elif event == "error":
            return data

    return final
