"""Server-Sent Events framing and parsing."""

from __future__ import annotations

import json
from typing import Any


def sse_format(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame (event + JSON data line)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_sse_frame(frame: str) -> tuple[str, dict[str, Any]]:
    """Parse ``event:`` / ``data:`` lines from a single SSE frame."""
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
    return event, data


def remap_frame_for_mcp_client(frame: str) -> str:
    """Pass through ``meta`` / ``delta`` / ``done`` frames (already standard-shaped)."""
    return frame
