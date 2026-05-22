"""HTTP POST /ask — JSON or SSE (layer-rag-query correlation pattern)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.correlation import (
    FORBIDDEN_BODY_DETAIL,
    UserContext,
    check_forbidden_body_keys,
    parse_http_correlation,
    parse_http_user,
    resolve_conversation_id,
    response_correlation_headers,
)
from app.mcp_server import mcp
from app.pipeline import ask_repo_impl
from app.streaming import stream_ask_repo_events


def _wants_stream(request: Request, body: dict[str, Any]) -> bool:
    if body.get("stream"):
        return True
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept


def http_ask_body(body: dict[str, Any]) -> tuple[str | None, str, str | None]:
    check_forbidden_body_keys(body)
    question = (body.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    repo = body.get("repo")
    if repo is not None and not str(repo).strip():
        repo = None
    conversation_id = body.get("conversation_id")
    if conversation_id is not None and not str(conversation_id).strip():
        conversation_id = None
    return repo, question, conversation_id


def _http_ask_context(request: Request, conversation_id: str | None) -> dict[str, Any]:
    rid, sid, tid = parse_http_correlation(request)
    user = parse_http_user(request)
    conv = resolve_conversation_id(conversation_id, use_env=False)
    return {
        "request_id": rid,
        "session_id": sid,
        "trace_id": tid,
        "conversation_id_arg": conv,
        "user": user,
        "_response_headers": response_correlation_headers(rid, sid, tid, conv, user),
    }


def _stream_response(
    repo: str | None,
    question: str,
    extra: dict[str, Any],
) -> StreamingResponse:
    headers = extra.pop("_response_headers", {})
    headers["Cache-Control"] = "no-cache"
    headers["X-Accel-Buffering"] = "no"

    async def event_gen() -> AsyncIterator[str]:
        async for chunk in stream_ask_repo_events(repo, question, **extra):
            yield chunk

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


@mcp.custom_route("/ask", methods=["POST"])
async def http_ask(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"detail": "body must be a JSON object"}, status_code=400)

    try:
        repo, question, conversation_id = http_ask_body(body)
    except ValueError as e:
        detail = FORBIDDEN_BODY_DETAIL if str(e) == FORBIDDEN_BODY_DETAIL else str(e)
        return JSONResponse({"detail": detail}, status_code=400)

    ctx = _http_ask_context(request, conversation_id)
    resp_headers = ctx.pop("_response_headers")

    if _wants_stream(request, body):
        return _stream_response(repo, question, ctx)

    result = await anyio.to_thread.run_sync(partial(ask_repo_impl, repo, question, **ctx))
    return JSONResponse(result, headers=resp_headers)
