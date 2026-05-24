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
| `meta` | Correlation ids, `is_new_conversation`, `user`, `route` (deterministic tool routing), `tool` (`name`: `github_search`, `type`: `github`, `version`: `v1`), `rewrite` (question), optional `github` (`repos`, `repo`, `scope`) |
| `answer` | `text`, `citations[]` with `cite_id`, `source`, `text` |
| `follow_up_questions` | string array |
| `latency_ms` | `total` plus `tool_github_search` with `retrieve_rerank`, `chat`, `follow_up_chat`, `total` |
| `usage` | `total` plus `tool_github_search` with optional `chat` / `follow_up_chat` and nested `total` |
| `status` | `ok`, `state`, `code` (`ok` / `failed`; `message` on failure) |
| `type` | `"done"` on stream terminal event only |

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
| `done` | Full tool payload | Same as buffered `structuredContent` plus `"type": "done"` |
| `error` | JSON-RPC 2.0 error | `error.data` may contain the failed tool payload (`status.ok: false`) |

Stdio MCP stream uses progress notifications for phases; HTTP SSE does not emit separate `status` events.

Optional headers: `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`.

---

## Related docs

- [smoke-test.md](smoke-test.md)
- [design.md](design.md)
- [log-json-schema.md](log-json-schema.md)
- [README.md](../README.md)

## response 
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
      "name":"ask_repo",
      "arguments":{
        "question":"introduce this huntAi project",
        "stream":true,
        "conversation_id":"conv_smoke_1s"
      }
    }
  }'

{
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
      "reason": "Deterministic: HuntAI/layer repo architecture question",
      "source": "deterministic_rule"
    },
    "tool": {
      "name": "github_search",
      "type": "github",
      "version": "v1"
    },
    "rewrite": "introduce this huntai project",
    "github": {
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
      ],
      "scope": "all"
    }
  },
  "answer": {
    "text": "HuntAI is a private AI assistant platform combining a Next.js frontend, FastAPI gateway layer, orchestrator services, GitHub/RAG tools, GPU-aware vLLM inference gateways, Qdrant vector retrieval, and k3s-based infrastructure.\n\nKey components include:\n\n- layer-web-v1: Next.js 15 chat application and frontend UI.\n- layer-gateway-api-v1: FastAPI BFF gateway handling authentication, request normalization, retries, SSE streaming, and orchestrator communication.\n- layer-orchestrator-v1: AI orchestration service coordinating chat completions, routing, and RAG workflows.\n- layer-rag-query-v1: Retrieval-Augmented Generation service using hybrid retrieval and reranking.\n- layer-gateway-inference-v1: GPU-aware routing gateway for distributed vLLM inference.\n- layer-gateway-embed-v1: Embedding gateway for distributed embedding inference.\n- layer-gateway-reranker-v1: Reranker gateway for semantic reranking workloads.\n- layer-rag-ingest-v1: Ingestion pipeline for preparing and indexing RAG documents into Qdrant.\n- k3s: Kubernetes infrastructure and GPU node orchestration.\n- layer-grafana-loki-central-logger: Centralized structured logging pipeline for Grafana Loki observability.\n\nThe overall architecture focuses on scalable AI inference, retrieval-augmented generation, observability, distributed GPU routing, and production-grade AI platform infrastructure.",
    "citations": [
      {
        "cite_id": 1,
        "source": "layer-mcp-github-v1 README",
        "text": "# layer-mcp-github ..."
      },
      {
        "cite_id": 2,
        "source": "layer-web-v1 README",
        "text": "# HuntAI ..."
      },
      {
        "cite_id": 3,
        "source": "layer-gateway-api-v1 README",
        "text": "# layer-gateway-api-v1 ..."
      },
      {
        "cite_id": 4,
        "source": "layer-orchestrator-v1 README",
        "text": "# layer-orchestrator-v1 ..."
      },
      {
        "cite_id": 5,
        "source": "layer-rag-query-v1 README",
        "text": "# layer-rag-query ..."
      },
      {
        "cite_id": 6,
        "source": "layer-gateway-inference-v1 README",
        "text": "# layer-gateway-inference-v1 ..."
      },
      {
        "cite_id": 7,
        "source": "layer-gateway-embed-v1 README",
        "text": "# layer-gateway-embed-v1 ..."
      },
      {
        "cite_id": 8,
        "source": "layer-gateway-reranker-v1 README",
        "text": "# layer-gateway-reranker-v1 ..."
      },
      {
        "cite_id": 9,
        "source": "layer-rag-ingest-v1 README",
        "text": "# RAG Ingest Pipeline ..."
      },
      {
        "cite_id": 10,
        "source": "k3s README",
        "text": "# k3s server + GPU agents ..."
      },
      {
        "cite_id": 11,
        "source": "layer-grafana-loki-central-logger README",
        "text": "# tb-loki-central-logger ..."
      }
    ]
  },
  "follow_up_questions": [
    "How does the orchestrator coordinate RAG and LLM workflows?",
    "Why use separate inference, embedding, and reranker gateways?",
    "How does HuntAI implement observability and structured logging?"
  ],
  "latency_ms": {
    "total": 13069,
    "tool_github_search": {
      "retrieve_rerank": 3832,
      "chat": 7893,
      "follow_up_chat": 1328,
      "total": 13069
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 580,
      "completion_tokens": 56,
      "total_tokens": 636
    },
    "tool_github_search": {
      "follow_up_chat": {
        "prompt_tokens": 580,
        "completion_tokens": 56,
        "total_tokens": 636
      },
      "total": {
        "prompt_tokens": 580,
        "completion_tokens": 56,
        "total_tokens": 636
      }
    }
  },
  "status": {
    "ok": true,
    "state": "completed",
    "code": "ok"
  },
  "type": "done"
}