# layer-mcp-github

MCP server that answers natural-language questions about a **fixed set of GitHub repos**. It pulls README + code search from GitHub, synthesizes an answer through your **LLM gateway** (`POST /v1/chat/completions`), and returns RAG-style JSON with numbered citations and GitHub URLs.

| Docs | Contents |
|------|----------|
| [schema.md](docs/schema.md) | `POST /ask` and MCP `ask_repo` contract |
| [design.md](docs/design.md) | Architecture, streaming, config, `app/` layout |
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
| **MCP + HTTP** | `python -m app.main --http` → `/mcp` and `POST /ask` |

Required env: `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`. Optional: `HTTP_HOST`, `HTTP_PORT`, `LLM_MODEL`, … — see [`.env.example`](.env.example).

## Allowlist

Edit `ALLOWED_REPOS` in [`app/repo_allowlist.py`](app/repo_allowlist.py) and restart the server.

Today: **9** repos under `GITHUB_OWNER`. See [schema.md](docs/schema.md) for `owner/name` rules.

## MCP tool: `ask_repo`

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `question` | yes | — | Natural-language question |
| `repo` | no | all allowlisted | Short name or `owner/name` |
| `stream` | no | `false` | `true` → progress + `answer_delta` logs; same final JSON |
| `request_id` | no | env / UUID | `X-Request-Id` on gateway |
| `session_id` | no | env / UUID | `X-Session-Id` |
| `trace_id` | no | env / null | `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway thread id |

`ask_repo_stream` is an alias for `ask_repo` with `stream: true`.

### HTTP `POST /ask`

Correlation and user context via **headers** (`X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Roles`, …). Set `"stream": true` or `Accept: text/event-stream` for SSE. See [smoke-test.md](docs/smoke-test.md) §5.

### MCP over HTTP (`--http`)

JSON-RPC on `POST /mcp` (no trailing slash). `tools/call` → `ask_repo`.

### Response fields

`ok`, `repos`, `answer`, `citations`, `follow_up_questions`, `latency_ms`, `usage`, `request_id`, `session_id`, `trace_id`, `conversation_id`.

## Project layout

```text
app/
├── main.py            # entry (stdio / --http MCP)
├── mcp_server.py      # FastMCP instance
├── tools.py           # ask_repo MCP tools
├── http_routes.py     # POST /ask
├── repo_allowlist.py  # ALLOWED_REPOS
├── allowlist.py       # resolve_repo / resolve_repos
├── pipeline.py        # ask_repo_impl
├── streaming.py       # MCP stream consumer
├── github_client.py   # README + code search
├── llm.py             # gateway chat / stream
├── correlation.py     # ids for MCP + gateway
├── config.py          # env, prompts
└── citations.py       # [n] sources
```

## Cursor

Enable MCP server **layer-github**. Examples:

- `Use ask_repo: What is the whole project design?`
- `Use ask_repo with stream true on layer-orchestrator-v1: how does routing work?`

## Docker

```bash
docker pull YOUR_DOCKERHUB_USER/layer-mcp-github:latest
docker run -p 8000:8000 --env-file .env YOUR_DOCKERHUB_USER/layer-mcp-github:latest
```

Image runs `python -m app.main --http` (MCP on port **8000**). Gateway URL must be reachable from the container.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Empty curl body | Use `/mcp` not `/mcp/` |
| No `answer` | `LLM_GATEWAY_BASE_URL` in `.env`; restart server |
| `repo not allowed` | Name in `ALLOWED_REPOS`; owner = `GITHUB_OWNER` |
| Slow default query | 9 repos; pass `"repo"` to narrow |
| Stale behavior | Restart after code changes |
