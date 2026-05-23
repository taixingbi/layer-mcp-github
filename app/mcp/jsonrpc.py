"""JSON-RPC 2.0 helpers for MCP HTTP responses."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse

JSONRPC_VERSION = "2.0"

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Implementation-defined server errors (-32000 .. -32099)
SERVER_ERROR = -32000


def request_id_from(body: Any) -> str | int | None:
    """Extract JSON-RPC ``id`` from a parsed request object (may be ``null``)."""
    if isinstance(body, dict) and "id" in body:
        return body.get("id")
    return None


def error_object(
    code: int,
    message: str,
    *,
    data: Any = None,
) -> dict[str, Any]:
    """Build the JSON-RPC ``error`` object."""
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def error_payload(
    rpc_id: str | int | None,
    code: int,
    message: str,
    *,
    data: Any = None,
) -> dict[str, Any]:
    """Full JSON-RPC error response object."""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": rpc_id,
        "error": error_object(code, message, data=data),
    }


def error_response(
    rpc_id: str | int | None,
    code: int,
    message: str,
    *,
    data: Any = None,
    status_code: int = 200,
) -> JSONResponse:
    """Starlette JSON response with a JSON-RPC 2.0 error body."""
    return JSONResponse(
        error_payload(rpc_id, code, message, data=data),
        status_code=status_code,
    )


def tool_failure_message(result: dict[str, Any]) -> str:
    """Human-readable message from an ask_repo ``fail()`` dict."""
    return str(result.get("error") or "Tool execution failed")


def sse_error_frame(
    rpc_id: str | int | None,
    code: int,
    message: str,
    *,
    data: Any = None,
) -> str:
    """SSE ``error`` event whose data is a JSON-RPC 2.0 error object."""
    from app.ask.sse import sse_format

    return sse_format("error", error_payload(rpc_id, code, message, data=data))
