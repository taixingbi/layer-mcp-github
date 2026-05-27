"""SSE streaming and MCP stream consumer."""

from __future__ import annotations

import json
import time
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
from mcp.server.fastmcp import Context

from app.clients.llm import generate_follow_ups, iter_chat_completion_stream
from app.observability.correlation import UserContext, is_new_conversation, resolve_correlation
from app.observability.log_context import bind_ask_context

from .common import (
    chat_messages,
    httpx_error_message,
    log_ask_done,
    log_ask_exception,
    log_ask_fail,
    log_ask_github_done,
    log_ask_start,
    resolve_ask_scope_or_error,
    tool_error_response,
)
from .pipeline import finish_github_search_result, gather_github_evidence
from .response import stream_delta_event, stream_meta_event
from .sse import parse_sse_frame, sse_format


async def stream_github_search_events(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    user: UserContext | None = None,
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    http_method: str = "-",
    http_path: str = "-",
    tool_name: str = "github_search",
    jsonrpc_id: str | int | None = None,
) -> AsyncIterator[str]:
    """Yield SSE: ``meta`` (once), ``delta`` (answer text chunks), ``done`` (full payload)."""
    from app.mcp.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, sse_error_frame

    rid, sid, tid, conv = resolve_correlation(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id_arg,
    )
    new_conv = is_new_conversation(conversation_id_arg)

    async def _notify_status(phase: str, data: dict[str, Any]) -> None:
        if on_status is None:
            return
        result = on_status(phase, data)
        if inspect.isawaitable(result):
            await result

    async def _emit_error(msg: str, *, code: int = INVALID_PARAMS) -> AsyncIterator[str]:
        log_ask_fail(msg, tool_name=tool_name, stream=True)
        err_body = tool_error_response(
            msg,
            repo=repo,
            request_id=rid,
            session_id=sid,
            trace_id=tid,
            conversation_id=conv,
            user=user,
            question=question,
            is_new_conv=new_conv,
        )
        yield sse_error_frame(jsonrpc_id, code, msg, data=err_body)

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
            stream_meta_event(
                request_id=rid,
                session_id=sid,
                trace_id=tid,
                conversation_id=conv,
                user=user,
                repos=scope.full_names,
                scope=scope.scope,
                question=question,
                is_new_conversation=new_conv,
                multi=scope.multi,
            ),
        )

        t0 = time.perf_counter()
        latency: dict[str, int] = {}
        chat_usage: dict[str, int] = {}
        follow_usage: dict[str, int] = {}
        citations: list[dict[str, Any]] = []
        readmes: dict[str, str] = {}
        code_hits: list[dict[str, str]] = []
        answer = ""
        follow_ups: list[str] = []

        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as client:
                await _notify_status("github_readme", {"repos": scope.full_names})

                citations, user_body, gh_latency, readmes, code_hits = gather_github_evidence(
                    client, scope.full_names, question, scope.multi
                )
                latency.update(gh_latency)
                log_ask_github_done(len(citations), gh_latency, stream=True)

                await _notify_status("chat_stream", {})

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
                        yield sse_format("delta", stream_delta_event(text))
                    elif kind == "usage":
                        chat_usage = payload
                    elif kind == "done":
                        answer = str(payload)

                latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

                await _notify_status("follow_up_chat", {})

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
            msg = httpx_error_message(e)
            err_body = tool_error_response(
                msg,
                repo=repo,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
                conversation_id=conv,
                user=user,
                question=question,
                is_new_conv=new_conv,
            )
            yield sse_error_frame(jsonrpc_id, INTERNAL_ERROR, msg, data=err_body)
            return

        result = finish_github_search_result(
            full_names=scope.full_names,
            scope=scope.scope,
            multi=scope.multi,
            question=question,
            is_new_conv=new_conv,
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
            user=user,
        )
        log_ask_done(
            scope,
            tool_name=tool_name,
            stream=True,
            user=user,
            citation_count=len(citations),
            follow_up_count=len(follow_ups),
            latency_ms=latency,
        )
        yield sse_format("done", result)


async def github_search_mcp_stream(
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
    tool_name: str = "github_search",
) -> dict[str, Any]:
    """Consume stream; MCP progress for phases; return final ``done`` payload only."""
    from .response import build_tool_error

    final: dict[str, Any] = build_tool_error(
        "stream ended without result",
        request_id=request_id or "-",
        session_id=session_id or "-",
        trace_id=trace_id,
        conversation_id=conversation_id_arg or "-",
        question=question,
        is_new_conversation=is_new_conversation(conversation_id_arg),
    )
    step = 0
    total_steps = 4

    async def _report_phase(phase: str, _data: dict[str, Any]) -> None:
        nonlocal step
        if ctx:
            step += 1
            await ctx.report_progress(step, total_steps, phase)

    async for frame in stream_github_search_events(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id_arg=conversation_id_arg,
        http_method=http_method,
        http_path=http_path,
        tool_name=tool_name,
        on_status=_report_phase if ctx else None,
    ):
        event, data = parse_sse_frame(frame)

        if ctx:
            if event == "delta":
                text = (data.get("answer") or {}).get("text") or ""
                if text:
                    await ctx.info(json.dumps({"type": "answer_delta", "text": text}))
            elif event == "error":
                err = data.get("error")
                msg = err.get("message", "stream error") if isinstance(err, dict) else str(
                    data.get("error", "stream error")
                )
                await ctx.error(msg)
                return data.get("data") if isinstance(data.get("data"), dict) else data

        if event == "done":
            final = data
        elif event == "error":
            return data.get("data") if isinstance(data.get("data"), dict) else data

    return final
