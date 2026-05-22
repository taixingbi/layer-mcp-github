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

SYSTEM_PROMPT = """You answer questions about GitHub repositories using ONLY the numbered Sources below.
- Cite with bracket indices that match Sources, e.g. [1] for README, [2] for a file.
- Name which repo each point refers to when multiple repositories are in scope.
- If evidence is insufficient, say what is missing; do not invent features.
- Be concise (short paragraphs or bullets)."""

FOLLOW_UP_PROMPT = """Given a user question and answer about a GitHub repo, suggest exactly 3 short follow-up questions.
Return JSON only: {"follow_up_questions": ["...", "...", "..."]}"""

load_dotenv(ROOT / ".env")

HTTP_HOST = (os.environ.get("HTTP_HOST") or "127.0.0.1").strip()
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))
