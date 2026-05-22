"""POST /mcp with real SSE when Accept: text/event-stream and tools/call stream=true."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.correlation import (
    parse_http_correlation,
    parse_http_user,
    resolve_conversation_id,
    response_correlation_headers,
)
from app.streaming import sse_format, stream_ask_repo_events

STREAM_TOOLS = frozenset({"ask_repo", "ask_repo_stream"})


def _truthy_stream(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def accepts_event_stream(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept


def is_streaming_tools_call(body: dict[str, Any]) -> bool:
    if body.get("method") != "tools/call":
        return False
    params = body.get("params") or {}
    name = params.get("name")
    if name not in STREAM_TOOLS:
        return False
    if name == "ask_repo_stream":
        return True
    args = params.get("arguments") or {}
    return _truthy_stream(args.get("stream"))


def wants_mcp_sse(request: Request, body: dict[str, Any]) -> bool:
    return request.method == "POST" and accepts_event_stream(request) and is_streaming_tools_call(body)


def parse_tools_call_arguments(body: dict[str, Any]) -> tuple[str | None, str, dict[str, Any]]:
    params = body.get("params") or {}
    args = dict(params.get("arguments") or {})
    repo = args.get("repo")
    if repo is not None and not str(repo).strip():
        repo = None
    question = (args.get("question") or "").strip()
    if not question:
        raise ValueError("question is required in tools/call arguments")
    return repo, question, args


def tools_call_stream_kwargs(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    rid, sid, tid = parse_http_correlation(request)
    user = parse_http_user(request)
    conv = resolve_conversation_id(args.get("conversation_id"), use_env=False)
    return {
        "request_id": (args.get("request_id") or "").strip() or rid,
        "session_id": (args.get("session_id") or "").strip() or sid,
        "trace_id": (args.get("trace_id") or "").strip() or tid,
        "conversation_id_arg": conv,
        "user": user,
    }


def _map_frame_for_mcp_client(frame: str) -> str:
    """Use event name `delta` (not `answer_delta`) for MCP HTTP SSE clients."""
    event = ""
    data: dict[str, Any] = {}
    for line in frame.split("\n"):
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                data = {}
    if event == "answer_delta":
        return sse_format("delta", data)
    return frame


async def mcp_tools_call_sse(
    request: Request,
    body: dict[str, Any],
) -> AsyncIterator[str]:
    repo, question, args = parse_tools_call_arguments(body)
    extra = tools_call_stream_kwargs(request, args)

    async for frame in stream_ask_repo_events(repo, question, **extra):
        yield _map_frame_for_mcp_client(frame)


def mcp_streaming_response(request: Request, body: dict[str, Any]) -> StreamingResponse:
    rid, sid, tid = parse_http_correlation(request)
    user = parse_http_user(request)
    args = (body.get("params") or {}).get("arguments") or {}
    conv = resolve_conversation_id(args.get("conversation_id"), use_env=False)
    headers = response_correlation_headers(rid, sid, tid, conv, user)
    headers["Cache-Control"] = "no-cache"
    headers["X-Accel-Buffering"] = "no"

    return StreamingResponse(
        mcp_tools_call_sse(request, body),
        media_type="text/event-stream",
        headers=headers,
    )


def replay_request(request: Request, body_bytes: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(request.scope, receive)


async def delegate_to_streamable_mcp(
    request: Request,
    inner_asgi: Any,
    *,
    body: bytes | None = None,
) -> Response:
    """Forward to FastMCP StreamableHTTPASGIApp and return a Starlette Response."""
    status_code = 500
    headers: list[tuple[bytes, bytes]] = []
    body_parts: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = message["status"]
            headers[:] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    if body is not None:
        request = replay_request(request, body)

    await inner_asgi(request.scope, request.receive, send)

    decoded_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers}
    return Response(
        content=b"".join(body_parts),
        status_code=status_code,
        headers=decoded_headers,
        media_type=decoded_headers.get("content-type"),
    )
