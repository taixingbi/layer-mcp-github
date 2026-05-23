# layer-mcp-github-v1 — design

## Purpose

MCP server for natural-language Q&A over allowlisted GitHub repos, with LLM synthesis and citations.

**MCP** on stdio (Cursor) or `POST /v1/mcp` (`--http`). **Ops** routes on HTTP only: `/health`, `/ready`, `/metrics`, `/version`. No REST `/ask`.

## Architecture

```text
Client
  ├─ Cursor (stdio)     python -m app.main
  └─ curl               python -m app.main --http  →  POST /v1/mcp
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

| Path | Role |
|------|------|
| `main.py` | Entry |
| `config.py` | Env, ports, `MCP_HTTP_PATH` (`/v1/mcp`), retrieval limits |
| `mcp/app.py` | Starlette app, `/v1/mcp`, ops routes, SSE middleware |
| `mcp/ops.py` | `/health`, `/ready`, `/metrics`, `/version` |
| `version.py` | Reads `[project].version` from installed package (set in `pyproject.toml`) |
| `mcp/http.py` | Stream detection + SSE generator |
| `mcp/server.py` | FastMCP |
| `mcp/tools.py` | `ask_repo`, `ask_repo_stream` |
| `ask/pipeline.py` | Buffered `ask_repo_impl` |
| `ask/common.py` | Shared validation, logging, buffered LLM |
| `ask/prompts.py` | `SYSTEM_PROMPT`, `FOLLOW_UP_PROMPT` |
| `ask/sse.py` | SSE format/parse/remap |
| `ask/streaming.py` | SSE event generator + MCP stream consumer |
| `ask/citations.py` | `[n]` sources |
| `allowlist/repos.py` | `ALLOWED_REPOS` |
| `allowlist/resolve.py` | `resolve_repos` |
| `clients/github.py` | README + code search |
| `clients/llm.py` | Gateway |
| `observability/correlation.py` | Ids + optional `X-User-*` on `/v1/mcp` |
| `observability/logging_config.py` | stderr JSON logger `layer_mcp.github` |
| `observability/request_context.py` | contextvars for log correlation |
| `observability/log_context.py` | bind context + latency `extra` helpers |

## Streaming

| Mode | Behavior |
|------|----------|
| stdio + `stream: true` | MCP progress + logs; final JSON |
| HTTP `/v1/mcp` + SSE Accept + `stream: true` | `meta`, `delta`, `done` events |
| HTTP `/v1/mcp` buffered | JSON-RPC `structuredContent` |

## Observability

Structured **stderr JSON** logs (one object per line). Schema: [log-json-schema.md](log-json-schema.md). Key lines: `ask_repo start`, `ask_repo done`, `ask_repo stream *`, `mcp tools/call sse start`, `http request done`. Set `LOG_LEVEL=DEBUG` for more detail.

| Route | Purpose |
|-------|---------|
| `GET /health` | Liveness (200 if process up) |
| `GET /ready` | Readiness: env, `GET /user` GitHub auth, LLM gateway probe (200 or 503) |
| `GET /metrics` | Prometheus text exposition |
| `GET /version` | `service` + `version` JSON |

## Configuration

`GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL` required. `HTTP_HOST` / `HTTP_PORT` for `--http`. Optional: `LOG_LEVEL`, `LOG_TZ`.

## Design choices

1. **MCP-only surface** — One protocol; no parallel REST API.
2. **SSE middleware** — Bypasses MCP SDK `application/json` Accept check for real streaming.
3. **Allowlist in code** — `app/allowlist/repos.py`.
4. **Per-repo code search** — Avoids GitHub multi-repo 422.
