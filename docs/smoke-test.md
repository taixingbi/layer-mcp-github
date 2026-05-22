# Smoke test — layer-mcp-github

Run from project root with venv active. Requires `.env` with `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`.

```bash
source venv/bin/activate
python -m app.main --http
```

Startup should print MCP URL, LLM gateway, and default repo list.

---

## 1. Allowlist (`app/repo_allowlist.py`)

```bash
python3 -c "from app.repo_allowlist import ALLOWED_REPOS; print(len(ALLOWED_REPOS)); print('\n'.join(ALLOWED_REPOS))"
```

**Pass:** expected count (e.g. 9); includes `layer-orchestrator-v1`, `k3s`.

```bash
python3 -c "from app.allowlist import resolve_repos; r=resolve_repos(); assert r['ok']; print(len(r['full_names']), r['full_names'])"
```

**Pass:** same count under `GITHUB_OWNER` from `.env`.

---

## 2. MCP — list tools

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://127.0.0.1:8000/mcp | jq -r '.result.tools[].name' | sort
```

**Pass:** `ask_repo`, `ask_repo_stream`.

Use `/mcp` not `/mcp/`.

---

## 3. MCP — buffered (`stream: false`)

```bash
curl -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-1","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"What is this repo for? One sentence.","stream":false,"conversation_id":"conv_smoke_1","request_id":"req-smoke-1","session_id":"ses-smoke-1","trace_id":"trc-smoke-1"}}}' \
  http://127.0.0.1:8000/mcp | jq .
```

**Pass:** `.result.structuredContent` has `ok: true`, non-empty `answer`, `citations` (≥1), matching correlation ids.

---

## 4. MCP — stream (`stream: true`)

```bash
curl -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-1s","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"What is this repo for? One sentence.","stream":true,"conversation_id":"conv_smoke_1s"}}}' \
  http://127.0.0.1:8000/mcp | jq .
```

**Pass:** same final JSON in `.result.structuredContent` (`ok`, `answer`, `citations`).

---

## 5. HTTP — stream (`POST /ask`, SSE)

Per [schema.md](schema.md). Correlation and user context are **header-only**; `conversation_id` in body.

```bash
curl -N -sS --max-time 120 -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: req-abc123" \
  -H "X-Session-Id: ses-xyz789" \
  -H "X-Trace-Id: trc-001" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "repo": "layer-orchestrator-v1",
    "question": "What is this repo for? One sentence.",
    "stream": true,
    "conversation_id": "conv_smoke_1"
  }' | tee /tmp/github-ask-stream.txt
```

**Pass:** events `meta`, `status`, `answer_delta`, `done`; `meta` includes `request_id`, `session_id`, `trace_id`, `conversation_id`, `user_roles`.

**Full `done` JSON:**

```bash
awk '/^event: done$/{p=1} p&&/^data: /{sub(/^data: /,""); print}' /tmp/github-ask-stream.txt | tail -1 | jq .
```

---

## 6. MCP — correlation (`trace_id` optional)

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-corr","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"One sentence.","stream":false}}}' \
  http://127.0.0.1:8000/mcp | jq '.result.structuredContent | {request_id, session_id, trace_id, conversation_id}'
```

**Pass:** `request_id`, `session_id`, `conversation_id` non-empty strings; `trace_id` is `null` when not passed.

---

## 7. LLM gateway

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
python3 -c "from app.repo_allowlist import ALLOWED_REPOS; print('expect', len(ALLOWED_REPOS))"
```

```bash
curl -s --max-time 300 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-full","method":"tools/call","params":{"name":"ask_repo","arguments":{"question":"What is the whole project design?"}}}' \
  http://127.0.0.1:8000/mcp | jq '{ok: .result.structuredContent.ok, repos: (.result.structuredContent.repos | length)}'
```

**Pass:** `ok: true`, `repos` length equals `len(ALLOWED_REPOS)`.

---

## Server logs

During §3–5 expect GitHub readme/search and `POST .../v1/chat/completions` → `200 OK`.

---

## Failures

| Symptom | Check |
|---------|--------|
| Empty curl body | `/mcp` not `/mcp/` |
| `LLM gateway: (not set)` | `.env`; restart server |
| GitHub 401 | PAT `repo` scope |
| `repo not allowed` | `ALLOWED_REPOS` + `GITHUB_OWNER` |
| `400` correlation in body | Use `X-*` headers per [schema.md](schema.md) |
| Stale payload | Restart `python -m app.main --http` |

See [README](../README.md) · [design.md](design.md) · [schema.md](schema.md).
