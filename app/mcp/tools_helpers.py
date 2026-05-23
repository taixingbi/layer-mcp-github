"""Helpers for MCP tool handlers."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError


def ensure_tool_success(result: dict[str, Any]) -> dict[str, Any]:
    """Raise ``ToolError`` when ask_repo returns ``ok: false`` (MCP ``isError`` result)."""
    if result.get("ok") is False:
        raise ToolError(str(result.get("error") or "Tool execution failed"))
    return result
