"""Helpers for MCP tool handlers."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError


def ensure_tool_success(result: dict[str, Any]) -> dict[str, Any]:
    """Raise ``ToolError`` when ``status.ok`` is false (MCP ``isError`` result)."""
    status = result.get("status") or {}
    if status.get("ok") is False:
        raise ToolError(str(status.get("message") or "Tool execution failed"))
    return result
