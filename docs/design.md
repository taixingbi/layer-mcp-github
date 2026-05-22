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
| `ask_common.py` | Shared validation, logging, buffered LLM |
| `sse.py` | SSE format/parse/remap |
| `streaming.py` | SSE event generator + MCP stream consumer |
| `repo_allowlist.py` | `ALLOWED_REPOS` |
| `allowlist.py` | `resolve_repos` |
| `github_client.py` | README + code search |
| `llm.py` | Gateway |
| `correlation.py` | Ids + optional `X-User-*` on `/mcp` |
| `logging_config.py` | stderr JSON logger `layer_mcp.github` |
| `request_context.py` | contextvars for log correlation |
| `log_context.py` | bind context + latency `extra` helpers |
| `citations.py` | `[n]` sources |

## Streaming

| Mode | Behavior |
|------|----------|
| stdio + `stream: true` | MCP progress + logs; final JSON |
| HTTP `/mcp` + SSE Accept + `stream: true` | `meta`, `delta`, `done` events |
| HTTP `/mcp` buffered | JSON-RPC `structuredContent` |

## Observability

Structured **stderr JSON** logs (one object per line). Schema: [log-json-schema.md](log-json-schema.md). Key lines: `ask_repo start`, `ask_repo done`, `ask_repo stream *`, `mcp tools/call sse start`, `http request done`. Set `LOG_LEVEL=DEBUG` for more detail.

## Configuration

`GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL` required. `HTTP_HOST` / `HTTP_PORT` for `--http`. Optional: `LOG_LEVEL`, `LOG_TZ`.

## Design choices

1. **MCP-only surface** — One protocol; no parallel REST API.
2. **SSE middleware** — Bypasses MCP SDK `application/json` Accept check for real streaming.
3. **Allowlist in code** — `app/repo_allowlist.py`.
4. **Per-repo code search** — Avoids GitHub multi-repo 422.
