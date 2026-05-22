# layer-mcp-github

Ask questions about GitHub repos listed in [`tmp.md`](tmp.md). Uses GitHub (README + code search) and your LLM gateway. Docs: [`docs/design.md`](docs/design.md), [`docs/smoke-test.md`](docs/smoke-test.md).

**Default:** omit `repo` → searches all 9 repos. **Optional:** `"repo": "layer-orchestrator-v1"` for one repo.

## Setup

```bash
cd layer-mcp-github
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # GITHUB_TOKEN, GITHUB_OWNER, LLM_GATEWAY_BASE_URL
python server.py --http
```

Endpoints (HTTP mode):

- MCP: `http://127.0.0.1:8000/mcp` (no trailing slash)
- SSE: `http://127.0.0.1:8000/ask/stream`

Tools: `ask_repo` (buffered), `ask_repo_stream` (MCP logs). Curl examples: [`docs/smoke-test.md`](docs/smoke-test.md).

## Response

`ok`, `repos`, `answer` (with `[1]` cites), `citations` (GitHub URLs), `follow_up_questions`, `latency_ms`, `usage`.

## Allowlist (`tmp.md`)

`layer-web-v1`, `layer-gateway-api-v1`, `layer-orchestrator-v1`, `layer-rag-query-v1`, `layer-gateway-inference-v1`, `layer-gateway-embed-v1`, `layer-gateway-reranker-v1`, `layer-rag-ingest-v1`, `k3s`

## Cursor

Enable **layer-github** in MCP ([`.cursor/mcp.json`](.cursor/mcp.json)). Example: `Use ask_repo: What is the whole project design?`

## Docker Hub

CI pushes on every push to `main` (see [`.github/workflows/docker-push.yml`](.github/workflows/docker-push.yml)).

**Secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (Docker Hub access token).

**Images:** `<username>/layer-mcp-github:latest` and `<username>/layer-mcp-github:<git-sha>`

**Run published image:**

```bash
docker pull YOUR_DOCKERHUB_USER/layer-mcp-github:latest
docker run -p 8000:8000 --env-file .env YOUR_DOCKERHUB_USER/layer-mcp-github:latest
```

**Build locally:**

```bash
docker compose up --build
# or: docker build -t layer-mcp-github . && docker run -p 8000:8000 --env-file .env layer-mcp-github
```

`LLM_GATEWAY_BASE_URL` must be reachable from the container (LAN IP, cluster DNS, or `host.docker.internal`).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Empty HTTP body | Use `/mcp` not `/mcp/` |
| No `answer` | Set `LLM_GATEWAY_BASE_URL` in `.env`; restart server |
| Slow | Default hits 9 repos; add `"repo"` to narrow |
# layer-mcp-github
