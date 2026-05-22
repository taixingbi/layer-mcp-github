# layer-mcp-github — design

## Purpose

Let agents (Cursor) ask **natural-language questions** about a fixed set of **GitHub repos**, with answers grounded in repo evidence and synthesized by the **LLM gateway** the layer stack uses.

Python package under `app/`. **MCP** (stdio or `/mcp`) plus **`POST /ask`** (JSON or SSE).

## Scope

| In scope | Out of scope |
|----------|----------------|
| Repos in `app/repo_allowlist.py` | Arbitrary public GitHub search |
| README + per-repo code search | Full repo clone / tree index |
| LLM answer + GitHub citations | Vector DB / RAG ingest |
| MCP `ask_repo` + `POST /ask` | Arbitrary GitHub search |

## Architecture

```text
Client
  ├─ Cursor (stdio)     python -m app.main
  ├─ POST /ask          JSON or SSE
  └─ POST /mcp          streamable-http MCP
        │
        ▼
   tools.ask_repo  →  pipeline.ask_repo_impl  |  streaming.ask_repo_mcp_stream
        │
   ┌────┴────┐
   ▼         ▼
GitHub     LLM gateway
REST       POST /v1/chat/completions
```

## Modules

| Module | Role |
|--------|------|
| `main.py` | Entry; stdio or `--http` MCP |
| `mcp_server.py` | FastMCP (`HTTP_HOST`, `HTTP_PORT` for streamable-http) |
| `tools.py` | `ask_repo`, `ask_repo_stream` |
| `http_routes.py` | `POST /ask` |
| `correlation.py` | HTTP headers + MCP ids; `X-User-*` |
| `repo_allowlist.py` | `ALLOWED_REPOS` |
| `allowlist.py` | `resolve_repo`, `resolve_repos` |
| `pipeline.py` | `ask_repo_impl` (buffered) |
| `streaming.py` | Internal SSE frames + MCP progress/deltas |
| `github_client.py` | README + code search |
| `llm.py` | Gateway chat / stream |
| `correlation.py` | MCP tool correlation ids |
| `citations.py` | Numbered sources for LLM |
| `config.py` | Env, prompts, limits |

## Request flow

1. **Resolve repos** — `allowlist.resolve_repos`
2. **GitHub evidence** — README per repo; code search per repo
3. **Citations** — `[1]…[n]` merged for multi-repo
4. **LLM answer** — sources-only prompt
5. **Follow-ups** — second completion → 3 questions
6. **Response** — JSON in MCP `structuredContent`

## `ask_repo` contract

See [schema.md](schema.md).

| `stream` | Behavior |
|----------|----------|
| `false` | `ask_repo_impl` in worker thread; one JSON result |
| `true` | `ask_repo_mcp_stream`: progress + `answer_delta` logs; same final JSON |

## Configuration

| Variable | Required | Notes |
|----------|----------|-------|
| `GITHUB_TOKEN` | yes | PAT, `repo` scope |
| `GITHUB_OWNER` | yes | User or org |
| `LLM_GATEWAY_BASE_URL` | yes | e.g. `http://host:30180` |
| `HTTP_HOST` / `HTTP_PORT` | no | For `--http` MCP only (default `127.0.0.1:8000`) |

## Security

- Do not commit `.env`
- Only `ALLOWED_REPOS` are queryable
- `--http` exposes MCP on the network — use policy/firewall as needed

## Repository layout

```text
layer-mcp-github/
├── app/          # Python package
├── Dockerfile
├── docker-compose.yml
├── docs/
│   ├── schema.md
│   ├── design.md
│   └── smoke-test.md
└── README.md
```

## Design choices

1. **MCP + `/ask`** — Cursor uses MCP; scripts may use `POST /ask` with the same pipeline.
2. **Allowlist in code** — Versioned with the server.
3. **Default = full allowlist** — `repo` narrows scope.
4. **Per-repo code search** — Avoids GitHub multi-repo 422.
