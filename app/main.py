#!/usr/bin/env python3
"""Entry point: stdio MCP or streamable HTTP MCP (--http)."""

from __future__ import annotations

import app.mcp.tools  # noqa: F401 — register tools
from app.allowlist import ALLOWED_REPOS, allowed_short_names, resolve_repo, resolve_repos
from app.ask.pipeline import ask_repo_impl
from app.clients.llm import llm_gateway_base
from app.config import HTTP_PORT, MCP_HTTP_PATH
from app.mcp.server import mcp

__all__ = [
    "ALLOWED_REPOS",
    "ask_repo_impl",
    "mcp",
    "resolve_repo",
    "resolve_repos",
    "allowed_short_names",
]


def _run_server() -> None:
    """Start stdio MCP or HTTP MCP server after configuring stderr JSON logging."""
    import sys

    from app.observability.logging_config import setup_logging

    setup_logging()

    if "--http" in sys.argv:
        llm = llm_gateway_base() or "(not set — github_search will fail)"
        default_repos = allowed_short_names()
        base = f"http://127.0.0.1:{HTTP_PORT}"
        print(f"MCP {base}{MCP_HTTP_PATH}  (stream: Accept SSE + stream:true)", flush=True)
        print(f"Ops  {base}/health  {base}/ready  {base}/metrics  {base}/version", flush=True)
        print(f"LLM gateway: {llm}", flush=True)
        print(f"Default repos ({len(default_repos)}): {', '.join(default_repos)}", flush=True)
        import anyio

        from app.mcp.app import run_mcp_http_server

        anyio.run(run_mcp_http_server)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    _run_server()
