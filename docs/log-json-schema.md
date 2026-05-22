# Log JSON schema (design)

Structured logs for **layer-mcp-github** are emitted by the stdlib logger `layer_mcp.github`, configured in [`app/logging_config.py`](../app/logging_config.py). This document describes the **on-the-wire JSON** shape (one UTF-8 JSON object per line), aligned with [layer-rag-query-v1](https://github.com/taixingbi/layer-rag-query-v1/blob/main/docs/log-json-schema.md).

## Goals

- **Machine-parseable**: single-line JSON suitable for `jq`, log agents, or downstream indexing.
- **Correlation**: tie log lines to MCP / HTTP work via `request_id`, `session_id`, optional `trace_id`, and `conversation_id` from [`app/request_context.py`](../app/request_context.py) (set by [`app/log_context.py`](../app/log_context.py)).
- **HTTP hints**: optional `method`, `path`, `status` for `POST /mcp` when context is bound.
- **No noise**: omit `error` when there is no exception (no `"error": null`).

## Sinks

| Sink | When |
|------|------|
| **stderr** | Always (INFO and above for the configured handler). |

Uvicorn access logs are disabled when running `--http`; use these JSON lines instead.

## Base record (every line)

All keys below are **always present** on normal log lines.

| Field | Type | Meaning |
|-------|------|---------|
| `ts` | string | ISO-8601 timestamp in **`America/New_York`** (override with env `LOG_TZ`). |
| `level` | string | Python log level name (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `request_id` | string | From request context, or `"-"` if unset. On HTTP `/mcp`, from `X-Request-Id` when sent, otherwise a server-generated UUID for that tools/call. |
| `session_id` | string | From request context when `request_id` is set; otherwise `"-"`. On HTTP `/mcp`, from `X-Session-Id` when sent, otherwise server-generated. |
| `trace_id` | string | From request context when set, else `"-"`. On HTTP `/mcp`, from optional `X-Trace-Id`; forwarded to the LLM gateway when present. |
| `user_id` | string | From request context when set, else `"-"`. On HTTP `/mcp`, from optional `X-User-Id`. |
| `conversation_id` | string | From tool args / `X-Conversation-Id` flow; else `"-"`. Resolved in [`app/correlation.py`](../app/correlation.py) and forwarded on gateway chat calls. |
| `method` | string | HTTP method from context, or `"-"` (stdio MCP uses `method=-`, `path=stdio`). |
| `path` | string | HTTP path from context, or `"-"`. |
| `status` | string | HTTP status from context, or from `logger.info(..., extra={"status": "200"})`, or `"-"`. |
| `message` | string | Human-oriented log text (`record.getMessage()`). |

## Optional: `error`

| Field | Type | When present |
|-------|------|----------------|
| `error` | string | Only when the log call includes exception info (`exc_info=True` or `logger.exception(...)`). Value is the formatted traceback string. |

## Optional: extension fields (`extra=`)

If the `LogRecord` has any of these attributes (via `logger.info(..., extra={...})`), they are **copied onto the JSON object** as top-level keys. They are omitted when not supplied.

Defined allowlist in code (`_EXTRA_JSON_FIELDS` in [`app/logging_config.py`](../app/logging_config.py)):

- `duration_ms` — mirrors `latency_total_ms` on `ask_repo done` / `ask_repo stream done` lines
- `latency_total_ms`, `latency_github_readme_ms`, `latency_github_search_ms`, `latency_chat_ms`, `latency_follow_up_chat_ms`
- `repo`, `repos`, `repo_count`, `scope` — allowlist resolution (`single` / `multi` / `all`)
- `stream` — `true` for SSE or MCP `stream: true`; `false` for buffered `ask_repo`
- `tool_name` — `ask_repo`, `ask_repo_stream`, etc.
- `phase` — pipeline step (`github_done`, `sse_start`, …)
- `citation_count`, `follow_up_count`
- `ok` — `true` on success lines; `false` on `ask_repo fail` warnings
- `reason`, `upstream_status`, `error_type`, `error_message`
- `user_roles`, `user_groups`, `user_teams` — from optional `X-User-*` headers on HTTP `/mcp`
- `backend` — project root on `logging configured` startup line

To add new structured fields for dashboards or alerts, extend that tuple in `logging_config.py` and pass them through `extra=`.

## Example lines

**Ask start (HTTP buffered tools/call):**

```json
{"ts": "2026-05-22T10:00:00.000000-04:00", "level": "INFO", "request_id": "req-abc", "session_id": "ses-xyz", "trace_id": "-", "user_id": "taixing", "conversation_id": "conv_deadbeef", "method": "POST", "path": "/mcp", "status": "-", "message": "ask_repo start scope=all repo_count=9 stream=false", "tool_name": "ask_repo", "stream": false, "scope": "all", "repo_count": 9, "repos": ["owner/repo1", "..."], "user_roles": "anyuser", "user_groups": "", "user_teams": ""}
```

**Ask finished:**

```json
{"ts": "2026-05-22T10:00:02.500000-04:00", "level": "INFO", "request_id": "req-abc", "session_id": "ses-xyz", "trace_id": "-", "user_id": "taixing", "conversation_id": "conv_deadbeef", "method": "POST", "path": "/mcp", "status": "-", "message": "ask_repo done citation_count=12 follow_up_count=3 latency_total_ms=2500", "ok": true, "tool_name": "ask_repo", "stream": false, "citation_count": 12, "follow_up_count": 3, "duration_ms": 2500, "latency_total_ms": 2500, "latency_github_readme_ms": 400, "latency_github_search_ms": 600, "latency_chat_ms": 1200, "latency_follow_up_chat_ms": 300}
```

**HTTP request wrapper:**

```json
{"ts": "2026-05-22T10:00:02.510000-04:00", "level": "INFO", "request_id": "-", "session_id": "-", "trace_id": "-", "user_id": "-", "conversation_id": "-", "method": "POST", "path": "/mcp", "status": "200", "message": "http request done status=200", "status": "200"}
```

**With exception:**

```json
{"ts": "2026-05-22T10:00:01.000000-04:00", "level": "ERROR", "request_id": "req-abc", "session_id": "ses-xyz", "trace_id": "-", "user_id": "-", "conversation_id": "conv_deadbeef", "method": "POST", "path": "/mcp", "status": "-", "message": "ask_repo upstream github status=403", "upstream_status": 403, "error_type": "HTTPStatusError", "error": "Traceback (most recent call last):\n  ..."}
```

## Configuration

| Env | Default | Effect |
|-----|---------|--------|
| `LOG_LEVEL` | `INFO` | Minimum level for stderr JSON |
| `LOG_TZ` | `America/New_York` | Timezone for `ts` |

## Related code

- Formatter and filter: [`app/logging_config.py`](../app/logging_config.py)
- Context setters: [`app/request_context.py`](../app/request_context.py), [`app/log_context.py`](../app/log_context.py)
- Log call sites: [`app/pipeline.py`](../app/pipeline.py), [`app/streaming.py`](../app/streaming.py), [`app/mcp_http.py`](../app/mcp_http.py), [`app/mcp_app.py`](../app/mcp_app.py)
- Startup: [`app/main.py`](../app/main.py) → `setup_logging()`
