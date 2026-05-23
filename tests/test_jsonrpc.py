"""JSON-RPC 2.0 response shape tests."""

import json

from starlette.testclient import TestClient

from app.config import MCP_HTTP_PATH
from app.mcp.app import create_mcp_app
from app.mcp.jsonrpc import INTERNAL_ERROR, PARSE_ERROR, error_payload


def test_error_payload_shape() -> None:
    body = error_payload("1", INTERNAL_ERROR, "Internal error")
    assert body == {
        "jsonrpc": "2.0",
        "id": "1",
        "error": {"code": INTERNAL_ERROR, "message": "Internal error"},
    }


def test_middleware_parse_error_is_jsonrpc() -> None:
    client = TestClient(create_mcp_app())
    r = client.post(MCP_HTTP_PATH, content=b"not json", headers={"Content-Type": "application/json"})
    data = r.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] is None
    assert data["error"]["code"] == PARSE_ERROR


def test_middleware_invalid_jsonrpc_version() -> None:
    client = TestClient(create_mcp_app())
    r = client.post(
        MCP_HTTP_PATH,
        json={"jsonrpc": "1.0", "id": "9", "method": "tools/list"},
    )
    data = r.json()
    assert data["id"] == "9"
    assert "error" in data
    assert data["error"]["code"] == -32600


def test_sse_error_frame_parses_as_jsonrpc() -> None:
    from app.mcp.jsonrpc import sse_error_frame

    frame = sse_error_frame("2", INTERNAL_ERROR, "boom", data={"ok": False})
    event, payload = __import__("app.ask.sse", fromlist=["parse_sse_frame"]).parse_sse_frame(frame)
    assert event == "error"
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "2"
    assert payload["error"]["message"] == "boom"
