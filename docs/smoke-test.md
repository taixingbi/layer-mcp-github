# Smoke test — layer-mcp-github

Quick checks after setup or code changes. Run from project root with venv active.

**Prereqs:** `.env` has `GITHUB_TOKEN`, `GITHUB_OWNER`, `LLM_GATEWAY_BASE_URL`. Server: `python server.py --http`.

Startup should show:

```text
LLM gateway: http://...
Default repos (9): layer-web-v1, ...
Stream SSE POST http://127.0.0.1:8000/ask/stream
```

---

## 1. Local (no HTTP)

```bash
source venv/bin/activate

python3 -c "from server import resolve_repos; r=resolve_repos(); assert r['ok'] and len(r['full_names'])==9; print('allowlist OK', len(r['full_names']))"

python3 -c "from server import resolve_repo; r=resolve_repo('not-real'); assert not r.get('ok'); print('reject OK')"
```

**Pass:** `allowlist OK 9`, `reject OK`.

---

## 2. MCP — list tools

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://127.0.0.1:8000/mcp | jq -r '.result.tools[].name' | sort
```

**Pass:** includes `ask_repo` and `ask_repo_stream`.

---

## 3. MCP — non-stream (single repo, faster)

```bash
curl -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-1","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"layer-orchestrator-v1","question":"What is this repo for? One sentence."}}}' \
  http://127.0.0.1:8000/mcp | jq .
```

**Pass:** in `.result.structuredContent`: `ok: true`, non-empty `answer`, `citations` (≥1), `follow_up_questions` (3 ideal).

---

## 4. MCP — allowlist rejection

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-2","method":"tools/call","params":{"name":"ask_repo","arguments":{"repo":"evil","question":"test"}}}' \
  http://127.0.0.1:8000/mcp | jq '.result.structuredContent | {ok, error, allowed: (.allowed|length)}'
```

**Pass:** `ok: false`, `error` mentions not allowed, `allowed` is 9.

---

## 5. HTTP SSE — stream

```bash
curl -N -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -d '{"repo":"layer-orchestrator-v1","question":"What is this repo for? One sentence."}' \
  http://127.0.0.1:8000/ask/stream | tee /tmp/github-mcp-stream.txt | head -40
```

**Pass (in first lines):** `event: status`, later `event: answer_delta`, eventually `event: done`.

**Final payload:**

```bash
awk '/^event: done$/{p=1} p&&/^data: /{sub(/^data: /,""); print}' /tmp/github-mcp-stream.txt | tail -1 | jq '{ok, answer: (.answer[:120]), citations: (.citations|length)}'
```

**Pass:** `ok: true`, non-empty `answer`.

---

## 6. LLM gateway only

```bash
source .env 2>/dev/null || set -a && source .env && set +a
curl -s "${LLM_GATEWAY_BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"ping"}],"max_tokens":8}' \
  | jq '{has_choices: (.choices|length>0)}'
```

**Pass:** `has_choices: true`.

---

## 7. Optional — full allowlist (slow)

Default question hits all 9 READMEs; expect **30–120s**.

```bash
curl -s --max-time 300 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-full","method":"tools/call","params":{"name":"ask_repo","arguments":{"question":"What is the whole project design?"}}}' \
  http://127.0.0.1:8000/mcp | jq '.result.structuredContent | {ok, repos: (.repos|length), answer: (.answer!=null)}'
```

**Pass:** `ok: true`, `repos: 9`, `answer: true`.

---

## Server logs (sanity)

While smoke 3 or 5 runs, terminal should show:

- Multiple `GET .../readme` (one per repo in scope)
- Per-repo `GET .../search/code?q=... repo:owner/name` (not one giant `OR` URL)
- `POST .../v1/chat/completions` with `200 OK`

---

## Failures

| Symptom | Check |
|---------|--------|
| Empty curl body | URL is `/mcp` not `/mcp/` |
| `LLM gateway: (not set)` | `.env` in project root; restart server |
| GitHub 401 | PAT + `repo` scope |
| No `answer`, old shape (`readme` only) | Stale process — restart `python server.py --http` |
| Stream has no `answer_delta` | Gateway `stream: true` support; test §6 |

See also [README](../README.md) and [design.md](design.md).
