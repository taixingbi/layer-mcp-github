"""Environment and constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

README_MAX = 8000
CODE_HITS_MAX = 15
SNIPPET_MAX = 400
LLM_CONTEXT_README_MAX = 6000
MULTI_REPO_README_MAX = 1200
MULTI_REPO_CODE_HITS_MAX = 20

load_dotenv(ROOT / ".env")

HTTP_HOST = (os.environ.get("HTTP_HOST") or "127.0.0.1").strip()
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))
MCP_HTTP_PATH = "/v1/mcp"
