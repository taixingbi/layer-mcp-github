"""MCP tool registration."""

from __future__ import annotations

from functools import partial
from typing import Any

import anyio
from mcp.server.fastmcp import Context

from app.mcp_server import mcp
from app.pipeline import ask_repo_impl
from app.streaming import ask_repo_mcp_stream


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

    Default (no repo): all repos in app/repo_allowlist.py. Set stream=true for token streaming via MCP progress/logs.

    Returns RAG-style payload: repos, answer, citations, follow_up_questions, latency_ms, usage, correlation ids.
    """
    if stream:
        return await ask_repo_mcp_stream(
            repo,
            question,
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id_arg=conversation_id,
            ctx=ctx,
            http_path="stdio",
            tool_name="ask_repo",
        )

    return await anyio.to_thread.run_sync(
        partial(
            ask_repo_impl,
            repo,
            question,
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id_arg=conversation_id,
            http_method="-",
            http_path="stdio",
            stream=False,
            tool_name="ask_repo",
        )
    )


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
    return await ask_repo_mcp_stream(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id_arg=conversation_id,
        ctx=ctx,
        tool_name="ask_repo_stream",
    )
