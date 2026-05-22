"""MCP streamable-http app with SSE tools/call support."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.config import HTTP_HOST, HTTP_PORT
from app.mcp_http import (
    accepts_event_stream,
    delegate_to_streamable_mcp,
    is_streaming_tools_call,
    mcp_streaming_response,
    replay_request,
)
from app.mcp_server import mcp


def _ensure_session_manager() -> None:
    mcp.streamable_http_app()


class McpStreamMiddleware(BaseHTTPMiddleware):
    """Intercept POST /mcp ask_repo stream before the MCP SDK Accept check."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if path != "/mcp" or request.method != "POST":
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes)
        except json.JSONDecodeError:
            return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse({"detail": "body must be a JSON object"}, status_code=400)

        if is_streaming_tools_call(body):
            if not accepts_event_stream(request):
                return JSONResponse(
                    {
                        "detail": (
                            "tools/call with stream:true requires Accept: text/event-stream "
                            "(the default MCP handler only accepts application/json)"
                        )
                    },
                    status_code=406,
                )
            return mcp_streaming_response(request, body)

        return await call_next(replay_request(request, body_bytes))


async def mcp_endpoint(request: Request) -> Response:
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp

    _ensure_session_manager()
    inner = StreamableHTTPASGIApp(mcp.session_manager)
    return await delegate_to_streamable_mcp(request, inner)


def create_mcp_app() -> Starlette:
    import app.tools  # noqa: F401

    _ensure_session_manager()

    routes: list[Route] = [
        Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    app = Starlette(debug=False, routes=routes, lifespan=lifespan)
    app.add_middleware(McpStreamMiddleware)
    return app


async def run_mcp_http_server() -> None:
    import uvicorn

    app = create_mcp_app()
    config = uvicorn.Config(app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
