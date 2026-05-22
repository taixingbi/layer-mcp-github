# HTTP and MCP contract

Aligned with [layer-rag-query-v1 `docs/schema.md`](https://github.com/taixingbi/layer-rag-query-v1/blob/main/docs/schema.md). Implementation: [`app/http_routes.py`](../app/http_routes.py), [`app/tools.py`](../app/tools.py), [`app/correlation.py`](../app/correlation.py).

---

## Endpoints

| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| `POST` | `/ask` | `application/json` or `text/event-stream` | GitHub evidence + LLM answer |
| `POST` | `/mcp` | MCP JSON-RPC | `tools/call` → `ask_repo` |

---

## `POST /ask`

### Request headers

#### Correlation (header-only)

| Header | Required | Notes |
|--------|----------|-------|
| `Content-Type` | yes | `application/json` |
| `X-Request-Id` | no | Omitted → server UUID |
| `X-Session-Id` | no | Omitted → server UUID |
| `X-Trace-Id` | no | Omitted → `trace_id: null` in body / SSE `meta` |

#### User context (header-only)

| Header | Required | Default | Notes |
|--------|----------|---------|-------|
| `X-User-Id` | no | `"-"` | Echoed on `200` |
| `X-User-Roles` | no | `anyuser` | Comma-separated |
| `X-User-Groups` | no | `""` | Comma-separated |
| `X-User-Teams` | no | `""` | Comma-separated |

**Forbidden in JSON body:** `request_id`, `session_id`, `trace_id`, `user_id`, `user_roles`, `user_groups`, `user_teams` → **400**.

#### Streaming

| Header | Notes |
|--------|-------|
| `Accept: text/event-stream` | Request SSE (OR body `"stream": true`) |

### Request body

| Field | Required | Default |
|-------|----------|---------|
| `question` | yes | — |
| `repo` | no | all allowlisted |
| `stream` | no | `false` |
| `conversation_id` | no | `conv_<hex>` |

### JSON response (`stream: false`)

Response headers: `X-Request-Id`, `X-Session-Id`, `X-Conversation-Id`, `X-User-Id`, optional `X-Trace-Id`.

Body: same shape as MCP `structuredContent` (`ok`, `answer`, `citations`, correlation ids, …).

### SSE events (`stream: true`)

| Event | Notes |
|-------|-------|
| `meta` | Correlation + `user_id`, `user_roles`, `user_groups`, `user_teams` |
| `status` | Phase progress |
| `answer_delta` | `{ "text": "..." }` |
| `done` | Full result object |
| `error` | `{ "ok": false, "error": "..." }` |

---

## MCP `ask_repo`

| Argument | HTTP equivalent |
|----------|-----------------|
| `request_id` | `X-Request-Id` |
| `session_id` | `X-Session-Id` |
| `trace_id` | `X-Trace-Id` |
| `conversation_id` | body `conversation_id` |
| (no user headers on MCP) | `X-User-*` on HTTP only |

See [smoke-test.md](smoke-test.md) for `curl` examples.
