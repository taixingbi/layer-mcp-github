# layer-mcp-github

MCP server that answers natural-language questions about a **fixed set of GitHub repos**. It pulls README + code search from GitHub, synthesizes an answer through your **LLM gateway** (`POST /v1/chat/completions`), and returns RAG-style JSON with numbered citations and GitHub URLs.

| Docs | Contents |
|------|----------|
| [schema.md](docs/schema.md) | MCP `ask_repo` contract |
| [design.md](docs/design.md) | Architecture, streaming, config, `app/` layout |
| [log-json-schema.md](docs/log-json-schema.md) | stderr JSON log fields |
| [smoke-test.md](docs/smoke-test.md) | curl checks for MCP + gateway |

**Default:** omit `repo` → all repos in [`app/repo_allowlist.py`](app/repo_allowlist.py). **Narrow:** `"repo": "layer-orchestrator-v1"` (short name or `owner/name`).

## Setup

```bash
cd layer-mcp-github
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # GITHUB_TOKEN, GITHUB_OWNER, LLM_GATEWAY_BASE_URL
```

| Mode | Command |
|------|---------|
| **Cursor** (stdio MCP) | `python -m app.main` — [`.cursor/mcp.json`](.cursor/mcp.json) |
| **MCP over HTTP** (curl) | `python -m app.main --http` → `POST /mcp` only |

Required env: `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`. Optional: `HTTP_HOST`, `HTTP_PORT`, `LLM_MODEL`, … — see [`.env.example`](.env.example).

## Allowlist

Edit `ALLOWED_REPOS` in [`app/repo_allowlist.py`](app/repo_allowlist.py) and restart the server.

Today: **9** repos under `GITHUB_OWNER`. See [schema.md](docs/schema.md).

## MCP tool: `ask_repo`

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `question` | yes | — | Natural-language question |
| `repo` | no | all allowlisted | Short name or `owner/name` |
| `stream` | no | `false` | `true` → SSE on `/mcp` when `Accept: text/event-stream` |
| `request_id` | no | env / UUID | Forwarded as `X-Request-Id` |
| `session_id` | no | env / UUID | Forwarded as `X-Session-Id` |
| `trace_id` | no | env / null | Forwarded as `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway thread id |

`ask_repo_stream` is an alias for `ask_repo` with `stream: true`.

### MCP over HTTP (`--http`)

`POST /mcp` (no trailing slash):

- **Buffered:** `Accept: application/json`, `"stream": false` → JSON-RPC `structuredContent`
- **Real SSE:** `Accept: text/event-stream` **and** `"stream": true` → `meta` / `delta` / `done` (smoke-test §4)

Optional headers on `/mcp`: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Roles`, …

### Response fields

`ok`, `repos`, `answer`, `citations`, `follow_up_questions`, `latency_ms`, `usage`, `request_id`, `session_id`, `trace_id`, `conversation_id`.

## Project layout

```text
app/
├── main.py            # entry (stdio / --http)
├── mcp_server.py      # FastMCP instance
├── mcp_app.py         # streamable-http + SSE middleware
├── mcp_http.py        # /mcp SSE tools/call
├── tools.py           # ask_repo MCP tools
├── repo_allowlist.py  # ALLOWED_REPOS
├── pipeline.py        # ask_repo_impl
├── streaming.py       # event pipeline
├── github_client.py
├── llm.py
├── correlation.py
├── config.py
└── citations.py
```

## Cursor

Enable MCP server **layer-github**. Examples:

- `Use ask_repo: What is the whole project design?`
- `Use ask_repo with stream true on layer-orchestrator-v1: how does routing work?`

## Docker

```bash
docker run -p 8000:8000 --env-file .env YOUR_DOCKERHUB_USER/layer-mcp-github:latest
```

Runs `python -m app.main --http` (MCP on port **8000**).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port in use | `lsof -ti :8000 \| xargs kill -9` then restart |
| Empty curl body | `/mcp` not `/mcp/` |
| No `answer` | `LLM_GATEWAY_BASE_URL` in `.env` |
| MCP stream JSON error | Restart server; use `Accept: text/event-stream` + `stream: true` |
