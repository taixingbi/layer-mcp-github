# MCP contract

Implementation: [`app/mcp/tools.py`](../app/mcp/tools.py), [`app/mcp/http.py`](../app/mcp/http.py), [`app/mcp/app.py`](../app/mcp/app.py). Runnable checks: [smoke-test.md](smoke-test.md).

**No REST API** — only stdio MCP (Cursor) or `POST /mcp` (streamable-http with `--http`).

---

## Endpoint

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/mcp` | JSON-RPC (buffered) or SSE (stream) |
| `GET` / `DELETE` | `/mcp` | MCP streamable-http session |

---

## Tools

| Tool | Notes |
|------|-------|
| `ask_repo` | Main tool; `stream: true` + `Accept: text/event-stream` → SSE |
| `ask_repo_stream` | Alias for `ask_repo(..., stream=true)` |

---

## `ask_repo` arguments

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `question` | yes | — | User question |
| `repo` | no | all allowlisted | Short name or `owner/name` |
| `stream` | no | `false` | `true` → SSE on HTTP `/mcp` when Accept allows |
| `request_id` | no | env / UUID | `X-Request-Id` to gateway |
| `session_id` | no | env / UUID | `X-Session-Id` |
| `trace_id` | no | env / `null` | `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway chat body |

---

## Buffered response (`stream: false`)

JSON-RPC result with `.result.structuredContent`:

`ok`, `answer`, `citations`, `follow_up_questions`, `latency_ms`, `usage`, correlation ids, `repos` / `repo`.

---

## Real SSE on `POST /mcp`

When **both** `Accept: text/event-stream` and `tools/call` with `stream: true` (or `ask_repo_stream`):

| Event | Notes |
|-------|-------|
| `meta` | Correlation ids; optional `user_*` from `X-User-*` headers |
| `status` | `github_readme`, `github_done`, `chat_stream`, … |
| `delta` | `{ "text": "..." }` per token |
| `done` | Full result object |
| `error` | `{ "ok": false, "error": "..." }` |

Optional headers: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`.

---

## Related docs

- [smoke-test.md](smoke-test.md)
- [design.md](design.md)
- [log-json-schema.md](log-json-schema.md)
- [README.md](../README.md)
