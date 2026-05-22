# layer-mcp-github — design

## Purpose

Let agents (Cursor) and scripts ask **natural-language questions** about a fixed set of **private GitHub repos**, with answers grounded in repo evidence and synthesized by the same **LLM gateway** the layer stack already uses.

Not a hosted GitHub MCP replacement. Not an orchestrator extension. Single Python process (`server.py`), minimal dependencies.

## Scope

| In scope | Out of scope |
|----------|----------------|
| Allowlisted repos in [`tmp.md`](../tmp.md) | Arbitrary public GitHub search |
| README + code search evidence | Cloning repos or full tree indexing |
| LLM answer + numbered GitHub citations | Vector DB / RAG ingest pipeline |
| MCP tools + HTTP SSE for curl | Changes to `layer-orchestrator-v1` |

## Architecture

```text
Client (Cursor stdio | curl MCP | curl SSE)
        │
        ▼
┌───────────────────┐
│  server.py        │
│  FastMCP          │
│  · ask_repo       │─── buffered JSON
│  · ask_repo_stream│─── MCP progress + logs
│  · POST /ask/stream ─── HTTP SSE
└─────────┬─────────┘
          │
    ┌─────┴─────┐
    ▼           ▼
 GitHub API   LLM gateway
 (REST)       POST /v1/chat/completions
```

## Request flow

1. **Resolve repos** — No `repo` → all short names in `tmp.md` under `GITHUB_OWNER`. Optional `repo` → one repo (validated against allowlist).
2. **GitHub evidence**
   - `GET /repos/{owner}/{repo}/readme` per repo (truncated for context).
   - `GET /search/code` per repo (avoids multi-repo `OR` queries that GitHub often rejects with 422).
3. **Citations** — Numbered `[1]…[n]` with GitHub repo root (README) and file URLs from search hits. Merged across repos when scope is “all”.
4. **LLM answer** — System prompt requires citing only provided sources. User message contains question + formatted sources/snippets.
5. **Follow-ups** — Second completion asks for 3 questions as JSON (`follow_up_questions`).
6. **Response** — RAG-style object: `answer`, `citations`, `repos`, `latency_ms`, `usage`, correlation ids.

## Entry points

| Surface | Transport | LLM answer mode |
|---------|-----------|-----------------|
| `ask_repo` | MCP `tools/call` | Non-stream (`stream: false`) |
| `ask_repo_stream` | MCP `tools/call` | Stream; tokens via MCP `info` logs + `report_progress` |
| `POST /ask/stream` | HTTP SSE | Stream; events `status`, `answer_delta`, `done` |

Follow-up LLM call is always non-stream in all modes.

## Response shape

Aligned with layer RAG/orchestrator answers:

- `ok`, `repos` (and `repo` when single-target)
- `answer` — text with `[n]` markers
- `citations[]` — `{ index, url, label, repo, type }`
- `follow_up_questions[]` (length 3 when parse succeeds)
- `latency_ms` — `github_readme`, `github_search`, `chat`, `follow_up_chat`, `total`
- `usage` — token counts per LLM call
- `request_id`, `session_id`, `trace_id`, `conversation_id`

Errors: `ok: false`, `error`, often `allowed` listing `tmp.md` names.

## Configuration

Loaded from project-root `.env` (see [`.env.example`](../.env.example)):

- **GitHub:** `GITHUB_TOKEN`, `GITHUB_OWNER`
- **LLM:** `LLM_GATEWAY_BASE_URL`, optional model/tokens/temperature, tracing headers, `LLM_API_KEY`
- **HTTP:** `HTTP_PORT` (default 8000)

Conversation id default: `github-all` (multi-repo) or `github-{owner-repo}` (single).

## Security

- PAT in `.env` only; never committed.
- Tool cannot query repos outside `tmp.md`.
- Custom `/ask/stream` route has no auth (local dev); bind is `127.0.0.1`.

## Repo layout

```text
layer-mcp-github/
├── server.py
├── tmp.md
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/docker-push.yml
├── docs/
└── README.md
```

## Design choices

1. **Single file** — Fast to ship and debug; no FastAPI envelope or multi-module split.
2. **Cursor-only orchestration** — No new service inside `layer-orchestrator-v1`.
3. **Default = full allowlist** — Matches “whole stack” questions; optional `repo` for focus.
4. **Per-repo code search** — Reliability over one combined GitHub query.
5. **Two curl paths** — MCP JSON for tools; SSE for terminal streaming without parsing MCP envelopes.

## Future (not implemented)

- Caching READMEs / search results
- Parallel GitHub fetches
- Auth on `/ask/stream`
- Official GitHub hosted MCP as primary runtime
