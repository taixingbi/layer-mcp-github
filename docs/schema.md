# MCP contract

Implementation: [`app/mcp/tools.py`](../app/mcp/tools.py), [`app/mcp/http.py`](../app/mcp/http.py), [`app/mcp/app.py`](../app/mcp/app.py). Runnable checks: [smoke-test.md](smoke-test.md).

**No REST API** — only stdio MCP (Cursor) or `POST /v1/mcp` (streamable-http with `--http`).

---

## Endpoint

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/mcp` | JSON-RPC (buffered) or SSE (stream) |
| `GET` / `DELETE` | `/v1/mcp` | MCP streamable-http session |

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
| `stream` | no | `false` | `true` → SSE on HTTP `/v1/mcp` when Accept allows |
| `request_id` | no | env / UUID | `X-Request-Id` to gateway |
| `session_id` | no | env / UUID | `X-Session-Id` |
| `trace_id` | no | env / `null` | `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway chat body |

---

## Buffered response (`stream: false`)

JSON-RPC result with `.result.structuredContent` (same object as stream `done`):

| Top-level | Description |
|-----------|-------------|
| `meta` | `request_id`, `session_id`, `trace_id`, `conversation_id`, `user`, `tool` (`name`, `type`: `github`, `version`: `v1`), optional `github` (`repos`, `repo`, `scope`) |
| `answer` | `text`, `citations[]` with `cite_id`, `source`, `text` |
| `follow_up_questions` | string array |
| `latency_ms` | `retrieve_rerank` (README + search), `chat`, `follow_up_chat`, `total` |
| `usage` | `chat`, optional `follow_up_chat`, `total` token counts |
| `status` | `ok`, `state` (`completed` or `failed`; `message` on failure) |

On tool failure the handler raises MCP `ToolError` → JSON-RPC **result** with `isError: true` and the same shape with `status.ok: false` (see [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#error-handling)).

---

## JSON-RPC 2.0 errors

Protocol and middleware errors use a standard JSON-RPC **error** object (HTTP body, `Content-Type: application/json`):

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "error": {
    "code": -32603,
    "message": "Internal error"
  }
}
```

| Code | When |
|------|------|
| `-32700` | Invalid JSON body |
| `-32600` | Not a JSON-RPC 2.0 object |
| `-32602` | Bad `tools/call` arguments (e.g. missing `question`) |
| `-32603` | Upstream / internal failure (SSE stream) |
| `-32000` | Server policy (e.g. stream without `Accept: text/event-stream`) |

Implementation: [`app/mcp/jsonrpc.py`](../app/mcp/jsonrpc.py), [`app/mcp/app.py`](../app/mcp/app.py) middleware.

---

## Real SSE on `POST /v1/mcp`

When **both** `Accept: text/event-stream` and `tools/call` with `stream: true` (or `ask_repo_stream`):

| Event | Body | Notes |
|-------|------|-------|
| `meta` | `{ "meta": { ... } }` | Once at start (no duplicate correlation fields on `delta` / `done`) |
| `delta` | `{ "answer": { "text": "..." } }` | Answer text chunks only |
| `done` | Full tool payload | Same shape as buffered `structuredContent` |
| `error` | JSON-RPC 2.0 error | `error.data` may contain the failed tool payload (`status.ok: false`) |

Stdio MCP stream uses progress notifications for phases; HTTP SSE does not emit separate `status` events.

Optional headers: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`.

---

## Related docs

- [smoke-test.md](smoke-test.md)
- [design.md](design.md)
- [log-json-schema.md](log-json-schema.md)
- [README.md](../README.md)
