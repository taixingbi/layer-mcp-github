"""MCP tool registration."""

from __future__ import annotations

from functools import partial
from typing import Any

import anyio
from mcp.server.fastmcp import Context

from app.ask.pipeline import ask_repo_impl
from app.ask.streaming import ask_repo_mcp_stream

from .server import mcp
from .tools_helpers import ensure_tool_success


def _correlation_kwargs(
    *,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    conversation_id: str | None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id_arg": conversation_id,
    }


@mcp.tool()
async def ask_repo(
    question: str,
    repo: str | None = None,
    stream: bool = False,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Answer a question about allowlisted GitHub repos (retrieve + LLM synthesis).

    Default (no repo): all repos in app/allowlist/repos.py. Set stream=true for token streaming via MCP progress/logs.

    Returns RAG-style payload: repos, answer, citations, follow_up_questions, latency_ms, usage, correlation ids.
    """
    corr = _correlation_kwargs(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
    )
    if stream:
        result = await ask_repo_mcp_stream(
            repo,
            question,
            ctx=ctx,
            http_path="stdio",
            tool_name="ask_repo",
            **corr,
        )
        return ensure_tool_success(result)

    result = await anyio.to_thread.run_sync(
        partial(
            ask_repo_impl,
            repo,
            question,
            http_method="-",
            http_path="stdio",
            stream=False,
            tool_name="ask_repo",
            **corr,
        )
    )
    return ensure_tool_success(result)


@mcp.tool()
async def ask_repo_stream(
    question: str,
    repo: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Alias for ask_repo(stream=true). Prefer ask_repo with stream in arguments."""
    result = await ask_repo_mcp_stream(
        repo,
        question,
        ctx=ctx,
        tool_name="ask_repo_stream",
        **_correlation_kwargs(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
        ),
    )
    return ensure_tool_success(result)
