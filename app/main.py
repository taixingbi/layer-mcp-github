#!/usr/bin/env python3
"""Entry point: stdio MCP or streamable HTTP MCP (--http)."""

from __future__ import annotations

import app.tools  # noqa: F401 — register tools
from app.allowlist import allowed_short_names, resolve_repo, resolve_repos
from app.config import HTTP_PORT
from app.llm import llm_gateway_base
from app.mcp_server import mcp
from app.pipeline import ask_repo_impl
from app.repo_allowlist import ALLOWED_REPOS

__all__ = [
    "ALLOWED_REPOS",
    "ask_repo_impl",
    "mcp",
    "resolve_repo",
    "resolve_repos",
    "allowed_short_names",
]


def _run_server() -> None:
    import sys

    if "--http" in sys.argv:
        llm = llm_gateway_base() or "(not set — ask_repo will fail)"
        default_repos = allowed_short_names()
        print(f"MCP http://127.0.0.1:{HTTP_PORT}/mcp  (stream: Accept SSE + stream:true)", flush=True)
        print(f"LLM gateway: {llm}", flush=True)
        print(f"Default repos ({len(default_repos)}): {', '.join(default_repos)}", flush=True)
        import anyio

        from app.mcp_app import run_mcp_http_server

        anyio.run(run_mcp_http_server)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    _run_server()
