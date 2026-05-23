"""MCP streamable-http app with SSE tools/call support."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.config import HTTP_HOST, HTTP_PORT, MCP_HTTP_PATH
from app.observability.logging_config import logger
from app.observability.request_context import bind_http_context

from .http import (
    accepts_event_stream,
    delegate_to_streamable_mcp,
    is_streaming_tools_call,
    mcp_streaming_response,
    replay_request,
)
from .jsonrpc import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    PARSE_ERROR,
    SERVER_ERROR,
    error_response,
    request_id_from,
)
from .ops import health, metrics, ready, version
from .server import mcp


class HttpLoggingMiddleware(BaseHTTPMiddleware):
    """Bind HTTP method/path for JSON logs and emit one line per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        with bind_http_context(request.method, path):
            response = await call_next(request)
            status = str(response.status_code)
            with bind_http_context(request.method, path, status=status):
                logger.info(
                    f"http request done status={status}",
                    extra={"status": status},
                )
            return response


def _ensure_session_manager() -> None:
    """Initialize FastMCP streamable HTTP session manager (idempotent)."""
    mcp.streamable_http_app()


class McpStreamMiddleware(BaseHTTPMiddleware):
    """Intercept POST MCP path ask_repo stream before the MCP SDK Accept check."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if path != MCP_HTTP_PATH or request.method != "POST":
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes)
        except json.JSONDecodeError:
            return error_response(None, PARSE_ERROR, "Parse error")

        if not isinstance(body, dict):
            return error_response(None, INVALID_REQUEST, "Invalid Request")

        rpc_id = request_id_from(body)
        if body.get("jsonrpc") != "2.0":
            return error_response(rpc_id, INVALID_REQUEST, "Invalid Request")

        if is_streaming_tools_call(body):
            if not accepts_event_stream(request):
                return error_response(
                    rpc_id,
                    SERVER_ERROR,
                    (
                        "tools/call with stream:true requires Accept: text/event-stream "
                        "(the default MCP handler only accepts application/json)"
                    ),
                )
            return mcp_streaming_response(request, body)

        return await call_next(replay_request(request, body_bytes))


async def mcp_endpoint(request: Request) -> Response:
    """Starlette route: delegate GET/POST/DELETE on MCP_HTTP_PATH to FastMCP streamable HTTP."""
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp

    _ensure_session_manager()
    inner = StreamableHTTPASGIApp(mcp.session_manager)
    return await delegate_to_streamable_mcp(request, inner)


def create_mcp_app() -> Starlette:
    """Build Starlette app with MCP routes and SSE/logging middleware."""
    import app.mcp.tools  # noqa: F401

    _ensure_session_manager()

    routes: list[Route] = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/ready", endpoint=ready, methods=["GET"]),
        Route("/metrics", endpoint=metrics, methods=["GET"]),
        Route("/version", endpoint=version, methods=["GET"]),
        Route(MCP_HTTP_PATH, endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    app = Starlette(debug=False, routes=routes, lifespan=lifespan)
    app.add_middleware(McpStreamMiddleware)
    app.add_middleware(HttpLoggingMiddleware)
    return app


async def run_mcp_http_server() -> None:
    """Run uvicorn with MCP HTTP app (no access log; stderr JSON only)."""
    import uvicorn

    app = create_mcp_app()
    config = uvicorn.Config(
        app,
        host=HTTP_HOST,
        port=HTTP_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()
