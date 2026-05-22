# layer-mcp-github — design

## Purpose

MCP server for natural-language Q&A over allowlisted GitHub repos, with LLM synthesis and citations.

**MCP only:** stdio (Cursor) or `POST /mcp` (`--http`). No REST `/ask`.

## Architecture

```text
Client
  ├─ Cursor (stdio)     python -m app.main
  └─ curl               python -m app.main --http  →  POST /mcp
        │
        ▼
   McpStreamMiddleware (SSE tools/call)
        │
        ▼
   tools.ask_repo  →  pipeline / streaming
        │
   ┌────┴────┐
   ▼         ▼
GitHub     LLM gateway
```

## Modules

| Module | Role |
|--------|------|
| `main.py` | Entry |
| `mcp_app.py` | Starlette app, `/mcp`, SSE middleware |
| `mcp_http.py` | Stream detection + SSE generator |
| `mcp_server.py` | FastMCP |
| `tools.py` | `ask_repo`, `ask_repo_stream` |
| `pipeline.py` | Buffered `ask_repo_impl` |
| `streaming.py` | Shared SSE event pipeline |
| `repo_allowlist.py` | `ALLOWED_REPOS` |
| `allowlist.py` | `resolve_repos` |
| `github_client.py` | README + code search |
| `llm.py` | Gateway |
| `correlation.py` | Ids + optional `X-User-*` on `/mcp` |
| `citations.py` | `[n]` sources |

## Streaming

| Mode | Behavior |
|------|----------|
| stdio + `stream: true` | MCP progress + logs; final JSON |
| HTTP `/mcp` + SSE Accept + `stream: true` | `meta`, `delta`, `done` events |
| HTTP `/mcp` buffered | JSON-RPC `structuredContent` |

## Configuration

`GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL` required. `HTTP_HOST` / `HTTP_PORT` for `--http`.

## Design choices

1. **MCP-only surface** — One protocol; no parallel REST API.
2. **SSE middleware** — Bypasses MCP SDK `application/json` Accept check for real streaming.
3. **Allowlist in code** — `app/repo_allowlist.py`.
4. **Per-repo code search** — Avoids GitHub multi-repo 422.
