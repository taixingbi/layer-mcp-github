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
| `github_search` | Main tool; default `stream: true` + `Accept: text/event-stream` → SSE. Set `stream: false` for buffered JSON |

---

## `github_search` arguments

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `question` | yes | — | User question |
| `repo` | no | all allowlisted | Short name or `owner/name` |
| `stream` | no | `true` | `false` → buffered JSON-RPC result; `true` (default) → SSE on HTTP `/v1/mcp` when Accept allows |
| `request_id` | no | env / UUID | `X-Request-Id` to gateway |
| `session_id` | no | env / UUID | `X-Session-Id` |
| `trace_id` | no | env / `null` | `X-Trace-Id` when set |
| `conversation_id` | no | `conv_<hex>` | Gateway chat body |

---

## Buffered response (`stream: false`)

JSON-RPC result with `.result.structuredContent` (same object as stream `done`):

| Top-level | Description |
|-----------|-------------|
| `meta` | Correlation ids, `is_new_conversation`, `user`, `route`, `tool` (`github_search`), `rewrite`, `github` (`scope`, `repos`, optional `repo`) |
| `answer` | `text`, `citations[]` with `cite_id` and `source` only |
| `follow_up_questions` | string array |
| `latency_ms` | `total` plus `tool_github_search` breakdown |
| `usage` | `total` token counts only |
| `status` | `ok`, `state`, `code` (`ok` / `failed`; `message` on failure) |

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

When **both** `Accept: text/event-stream` and `tools/call` with `github_search` (default stream=true, or explicit `stream: true`):

| Event | Body | Notes |
|-------|------|-------|
| `meta` | `{ "meta": { ... } }` | Once at start (no duplicate correlation fields on `delta` / `done`) |
| `delta` | `{ "answer": { "text": "..." } }` | Answer text chunks only |
| `done` | Full tool payload | Same fields as buffered `structuredContent` (no extra wrapper keys) |
| `error` | JSON-RPC 2.0 error | `error.data` may contain the failed tool payload (`status.ok: false`) |

Stdio MCP stream uses progress notifications for phases; HTTP SSE does not emit separate `status` events.

Optional headers: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`.

---

## Related docs

- [smoke-test.md](smoke-test.md)
- [design.md](design.md)
- [log-json-schema.md](log-json-schema.md)
- [README.md](../README.md)

## Example response

Stream request (all allowlisted repos). MCP returns tool fields under `.result` / `.result.structuredContent`; SSE emits `meta` → `delta` → `done` with the same payload on `done`.

```bash
curl -N -sS --max-time 120 -X POST http://192.168.86.179:30191/v1/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: req-mcp-stream-1" \
  -H "X-Session-Id: ses-mcp-stream-1" \
  -H "X-Trace-Id: trc-mcp-stream-1" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "jsonrpc":"2.0",
    "id":"smoke-1s",
    "method":"tools/call",
    "params":{
      "name":"github_search",
      "arguments":{
        "question":"introduce this huntAi project",
        "stream":true,
        "conversation_id":"conv_smoke_1s"
      }
    }
  }'
```

```json
{
  "jsonrpc": "2.0",
  "id": "smoke-1s",
  "result": {
    "meta": {
      "request_id": "req-mcp-stream-1",
      "session_id": "ses-mcp-stream-1",
      "trace_id": "trc-mcp-stream-1",
      "conversation_id": "conv_smoke_1s",
      "is_new_conversation": false,
      "user": {
        "id": "taixing",
        "roles": "hr",
        "groups": "engineering",
        "teams": "rag-platform"
      },
      "route": {
        "type": "tool",
        "tool": "github_search",
        "confidence": 0.99,
        "reason": "Deterministic multi-repo GitHub question",
        "source": "deterministic_rule"
      },
      "tool": {
        "name": "github_search",
        "type": "github",
        "version": "v1"
      },
      "rewrite": "introduce this huntAi project",
      "github": {
        "scope": "all",
        "repos": [
          "taixingbi/layer-mcp-github-v1",
          "taixingbi/layer-web-v1",
          "taixingbi/layer-gateway-api-v1",
          "taixingbi/layer-orchestrator-v1",
          "taixingbi/layer-rag-query-v1",
          "taixingbi/layer-gateway-inference-v1",
          "taixingbi/layer-gateway-embed-v1",
          "taixingbi/layer-gateway-reranker-v1",
          "taixingbi/layer-rag-ingest-v1",
          "taixingbi/k3s",
          "taixingbi/layer-grafana-loki-central-logger"
        ]
      }
    },
    "answer": {
      "text": "## Introduction to huntAi Project\n\nThe huntAi project consists of several interconnected components designed to facilitate natural language processing and artificial intelligence applications...",
      "citations": [
        {
          "cite_id": 1,
          "source": "layer-mcp-github-v1 README"
        },
        {
          "cite_id": 2,
          "source": "layer-web-v1 README"
        },
        {
          "cite_id": 3,
          "source": "layer-gateway-api-v1 README"
        },
        {
          "cite_id": 4,
          "source": "layer-orchestrator-v1 README"
        },
        {
          "cite_id": 5,
          "source": "layer-rag-query-v1 README"
        },
        {
          "cite_id": 6,
          "source": "layer-gateway-inference-v1 README"
        },
        {
          "cite_id": 7,
          "source": "layer-gateway-embed-v1 README"
        },
        {
          "cite_id": 8,
          "source": "layer-gateway-reranker-v1 README"
        },
        {
          "cite_id": 9,
          "source": "layer-rag-ingest-v1 README"
        },
        {
          "cite_id": 10,
          "source": "k3s README"
        },
        {
          "cite_id": 11,
          "source": "layer-grafana-loki-central-logger README"
        }
      ]
    },
    "follow_up_questions": [
      "What is the primary function of the Layer-MCP-GitHub-V1 component?",
      "Can you explain how the Layer-Orchestrator-V1 manages chat completions?",
      "Which tools are used for logging in the Layer-Grafana-Loki-Central-Logger component?"
    ],
    "latency_ms": {
      "total": 12683,
      "tool_github_search": {
        "retrieve_rerank": 4351,
        "chat": 6865,
        "follow_up_chat": 1420,
        "total": 12683
      }
    },
    "usage": {
      "total": {
        "prompt_tokens": 527,
        "completion_tokens": 65,
        "total_tokens": 592
      }
    },
    "status": {
      "ok": true,
      "state": "completed",
      "code": "ok"
    }
  }
}
```