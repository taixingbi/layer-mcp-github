# Smoke test — layer-mcp-github-v1

Run from project root with venv active. Requires `.env` with `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`.

```bash
source venv/bin/activate
lsof -ti :8000 | xargs kill -9 2>/dev/null; python -m app.main --http
```

Startup should print MCP URL, ops URLs, LLM gateway, and default repo list.

---

## 0. Ops endpoints (HTTP only)

```bash
curl -s http://127.0.0.1:8000/health | jq .
curl -s http://127.0.0.1:8000/version | jq .
curl -s http://127.0.0.1:8000/ready | jq .
curl -s http://127.0.0.1:8000/metrics | head
```

**Pass:** `/health` → `{"status":"ok",...}`; `/version` → `"version"` matches `[project].version` in `pyproject.toml` (after `pip install -e .`); `/ready` → `"status":"ready"` and all `checks` true when `.env` is valid; `/metrics` → Prometheus text including `layer_mcp_github_info`.

---

## 1. Allowlist (`app/allowlist/repos.py`)

```bash
python3 -c "from app.allowlist import ALLOWED_REPOS; print(len(ALLOWED_REPOS)); print('\n'.join(ALLOWED_REPOS))"
```

**Pass:** expected count (e.g. 9); includes `layer-orchestrator-v1`, `k3s`.

```bash
python3 -c "from app.allowlist import resolve_repos; r = resolve_repos(); assert r['ok']; print(len(r['full_names']), r['full_names'])"
```

**Pass:** same count under `GITHUB_OWNER` from `.env`.

---

## 2. MCP — list tools

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://127.0.0.1:8000/v1/mcp | jq -r '.result.tools[].name' | sort
```

**Pass:** `ask_repo`, `ask_repo_stream`.

Use `/v1/mcp` not `/v1/mcp/`.

---

## 3. MCP — buffered (`stream: false`)

```bash
curl -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":"smoke-1","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"introduce this huntAi project","stream":false,"conversation_id":"conv_smoke_1","request_id":"req-smoke-1","session_id":"ses-smoke-1","trace_id":"trc-smoke-1"}}}' \
  http://127.0.0.1:8000/v1/mcp | jq '.result.structuredContent | {ok, answer, citations}'
```

**Pass:** `ok: true`, non-empty `answer` and `citations`.

---

## 4. MCP — real SSE stream (`Accept: text/event-stream` + `stream: true`)

Requires `Accept: text/event-stream` and `"stream": true` on `ask_repo` (or `ask_repo_stream`). Events: `meta`, `status`, `delta`, `done`.

```bash
curl -N -sS --max-time 120 -X POST http://127.0.0.1:8000/v1/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: req-mcp-stream-1" \
  -H "X-Session-Id: ses-mcp-stream-1" \
  -H "X-Trace-Id: trc-mcp-stream-1" \
  -d '{
    "jsonrpc":"2.0",
    "id":"smoke-1s",
    "method":"tools/call",
    "params":{
      "name":"ask_repo",
      "arguments":{
        "repo":"layer-orchestrator-v1",
        "question":"introduce this huntAi project",
        "stream":true,
        "conversation_id":"conv_smoke_1s"
      }
    }
  }' | tee /tmp/mcp-stream.txt
```

**Pass:** SSE lines with `event: meta`, `event: delta`, `event: done`; `meta` has `request_id` `req-mcp-stream-1`.

**Final JSON from `done`:**

```bash
awk '/^event: done$/{p=1} p&&/^data: /{sub(/^data: /,""); print}' /tmp/mcp-stream.txt | tail -1 | jq '{ok, answer: (.answer|length), citations: (.citations|length)}'
```

---

## 5. MCP — correlation (`trace_id` optional)

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":"smoke-corr","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"One sentence.","stream":false}}}' \
  http://127.0.0.1:8000/v1/mcp | jq '.result.structuredContent | {request_id, session_id, trace_id, conversation_id}'
```

**Pass:** `request_id`, `session_id`, `conversation_id` non-empty strings; `trace_id` is `null` when not passed in arguments.

---

## 6. LLM gateway

```bash
set -a && source .env && set +a
curl -s "${LLM_GATEWAY_BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"ping"}],"max_tokens":8}' \
  | jq '{has_choices: (.choices|length>0)}'
```

**Pass:** `has_choices: true`.

---

## 7. Optional — all repos (slow)

```bash
python3 -c "from app.allowlist import ALLOWED_REPOS; print('expect', len(ALLOWED_REPOS))"
```

```bash
curl -N -sS --max-time 120 -X POST http://127.0.0.1:8000/v1/mcp \
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
  }' | tee /tmp/mcp-stream.txt
```

**Pass:** `ok: true`, `repos` length equals `len(ALLOWED_REPOS)`.

---

## Server logs

During §3–4 expect GitHub readme/search and `POST .../v1/chat/completions` → `200 OK`. §4 uses SSE on `/v1/mcp` (not JSON-RPC envelope).

---

## Failures

| Symptom | Check |
|---------|--------|
| `[errno 48] address already in use` | `lsof -ti :8000 \| xargs kill -9` then restart |
| Empty curl body | `/v1/mcp` not `/v1/mcp/` |
| `LLM gateway: (not set)` | `.env`; restart server |
| GitHub 401 | PAT `repo` scope |
| `repo not allowed` | `ALLOWED_REPOS` + `GITHUB_OWNER` |
| `Not Acceptable: Client must accept application/json` on `/v1/mcp` stream | Stale server — restart; startup must show `(stream: Accept SSE + stream:true)` |
| Stale payload | Restart `python -m app.main --http` |

See [README](../README.md) · [design.md](design.md) · [schema.md](schema.md).
