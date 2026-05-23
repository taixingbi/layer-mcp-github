curl -s --max-time 120 -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"smoke-1s","method":"tools/call","params":{"name":"ask_repo","arguments":{"question":"What is the whole project design?","stream":true}}}' \
  http://127.0.0.1:8000/mcp | jq .





curl -sS --max-time 120 -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Request-Id: req-abc123" \
  -H "X-Session-Id: ses-xyz789" \
  -H "X-Trace-Id: trc-001" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
  "repo": "layer-orchestrator-v1",
        "question": "introduce this huntAi project",
        "stream": false,
        "conversation_id": "conv_smoke_1"
    }
  }' | jq .




  curl -s http://127.0.0.1:8000/health | jq .
curl -s http://127.0.0.1:8000/version | jq .
curl -s http://127.0.0.1:8000/ready | jq .
curl -s http://127.0.0.1:8000/metrics | head


health version ready metrics