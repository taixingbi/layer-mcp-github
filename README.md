# layer-mcp-github

MCP server (**[layer-mcp-github-v1](https://github.com/taixingbi/layer-mcp-github-v1)**) that answers natural-language questions about a **fixed set of GitHub repos**. It pulls README + code search from GitHub, synthesizes an answer through your **LLM gateway** (`POST /v1/chat/completions`), and returns RAG-style JSON with numbered citations and GitHub URLs.

| Docs | Contents |
|------|----------|
| [schema.md](docs/schema.md) | MCP `github_search` contract |
| [design.md](docs/design.md) | Architecture, streaming, config, `app/` layout |
| [log-json-schema.md](docs/log-json-schema.md) | stderr JSON log fields |
| [smoke-test.md](docs/smoke-test.md) | curl checks for MCP + gateway |

**Default:** omit `repo` → all repos in [`app/allowlist/repos.py`](app/allowlist/repos.py). **Narrow:** `"repo": "layer-orchestrator-v1"` (short name or `owner/name`).

## Setup

```bash
cd layer-mcp-github-v1
python3 -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env   # GITHUB_TOKEN, GITHUB_OWNER, LLM_GATEWAY_BASE_URL
```

| Mode | Command |
|------|---------|
| **Cursor** (stdio MCP) | `python -m app.main` — [`.cursor/mcp.json`](.cursor/mcp.json) |
| **MCP over HTTP** (curl) | `python -m app.main --http` → `POST /v1/mcp`; ops: `/health`, `/ready`, `/metrics`, `/version` |

Required env: `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`. Optional: `HTTP_HOST`, `HTTP_PORT`, `LLM_MODEL`, … — see [`.env.example`](.env.example).

**Version:** edit `[project].version` in [`pyproject.toml`](pyproject.toml), then `pip install -e .` (or rebuild the Docker image). CI tags images `:VERSION` from the same file.

## Allowlist

Edit `ALLOWED_REPOS` in [`app/allowlist/repos.py`](app/allowlist/repos.py) and restart the server.

Today: **10** repos under `GITHUB_OWNER`. See [schema.md](docs/schema.md).

## MCP tool: `github_search`

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `question` | yes | — | Natural-language question |
| `repo` | no | all allowlisted | Short name or `owner/name` |
| `stream` | no | `true` | `false` → buffered JSON; `true` (default) → SSE on `/v1/mcp` with `Accept: text/event-stream` |
| `request_id` | no | env / UUID | Forwarded as `X-Request-Id` |
| `session_id` | no | env / UUID | Forwarded as `X-Session-Id` |
| `trace_id` | no | env / null | Forwarded as `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway thread id |

### MCP over HTTP (`--http`)

`POST /v1/mcp` (no trailing slash):

- **Buffered:** `Accept: application/json`, `"stream": false` → JSON-RPC `structuredContent`
- **Real SSE (default):** `Accept: text/event-stream` and omit `stream` (or set `"stream": true`) → `meta` / `delta` / `done` (smoke-test §4)

Optional headers on `/v1/mcp`: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Roles`, …

### Response fields

`ok`, `repos`, `answer`, `citations`, `follow_up_questions`, `latency_ms`, `usage`, `request_id`, `session_id`, `trace_id`, `conversation_id`.

## Project layout

```text
app/
├── main.py, config.py
├── ask/               # pipeline, streaming, citations, prompts, sse
├── mcp/               # server, app, http, tools
├── clients/           # github, llm
├── allowlist/         # repos, resolve
└── observability/     # correlation, logging, request context
```

## Cursor

Enable MCP server **layer-mcp-github-v1** (see [`.cursor/mcp.json`](.cursor/mcp.json)). Examples:

- `Use github_search: What is the whole project design?`
- `Use github_search on layer-orchestrator-v1: how does routing work?`

## Docker

```bash
docker compose up --build
# or
docker run -p 8000:8000 --env-file .env YOUR_DOCKERHUB_USER/layer-mcp-github-v1:latest
```

Runs `python -m app.main --http` (MCP on port **8000**). Image tags match [layer-rag-query-v1](https://github.com/taixingbi/layer-rag-query-v1) (`layer-mcp-github-v1:latest` on Docker Hub after CI push to `main`).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port in use | `lsof -ti :8000 \| xargs kill -9` then restart |
| Empty curl body | `/v1/mcp` not `/v1/mcp/` |
| No `answer` | `LLM_GATEWAY_BASE_URL` in `.env` |
| MCP stream JSON error | Restart server; use `Accept: text/event-stream` + `stream: true` |
