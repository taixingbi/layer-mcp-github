#!/usr/bin/env python3
"""Minimal stdio MCP: ask questions about allowlisted GitHub repos (tmp.md)."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parent
ALLOWLIST_PATH = ROOT / "tmp.md"
README_MAX = 8000
CODE_HITS_MAX = 15
SNIPPET_MAX = 400
LLM_CONTEXT_README_MAX = 6000

_SYSTEM_PROMPT = """You answer questions about GitHub repositories using ONLY the numbered Sources below.
- Cite with bracket indices that match Sources, e.g. [1] for README, [2] for a file.
- Name which repo each point refers to when multiple repositories are in scope.
- If evidence is insufficient, say what is missing; do not invent features.
- Be concise (short paragraphs or bullets)."""

_MULTI_REPO_README_MAX = 1200
_MULTI_REPO_CODE_HITS_MAX = 20

_FOLLOW_UP_PROMPT = """Given a user question and answer about a GitHub repo, suggest exactly 3 short follow-up questions.
Return JSON only: {"follow_up_questions": ["...", "...", "..."]}"""

load_dotenv(ROOT / ".env")

_HTTP_HOST = (os.environ.get("HTTP_HOST") or "127.0.0.1").strip()
_HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))

mcp = FastMCP(
    "layer-mcp-github",
    host=_HTTP_HOST,
    port=_HTTP_PORT,
    stateless_http=True,
    json_response=True,
)


def _allowed_short_names() -> list[str]:
    if not ALLOWLIST_PATH.is_file():
        return []
    lines = []
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if name and not name.startswith("#"):
            lines.append(name)
    return lines


def _github_owner() -> str:
    return (os.environ.get("GITHUB_OWNER") or "").strip()


def _github_token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or "").strip()


def _llm_gateway_base() -> str:
    return (os.environ.get("LLM_GATEWAY_BASE_URL") or "").strip().rstrip("/")


def _llm_model() -> str:
    return (os.environ.get("LLM_MODEL") or "Qwen/Qwen2.5-7B-Instruct").strip()


def _llm_api_key() -> str:
    return (os.environ.get("LLM_API_KEY") or "not-needed").strip()


def _llm_max_tokens() -> int:
    return int(os.environ.get("LLM_MAX_TOKENS", "1024"))


def _llm_temperature() -> float:
    return float(os.environ.get("LLM_TEMPERATURE", "0.7"))


def _llm_headers(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, str]:
    rid = (request_id or os.environ.get("LLM_REQUEST_ID") or "").strip() or str(uuid.uuid4())
    sid = (session_id or os.environ.get("LLM_SESSION_ID") or "").strip() or "layer-mcp-github"
    tid = (trace_id or os.environ.get("LLM_TRACE_ID") or "").strip() or rid
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Request-Id": rid,
        "X-Session-Id": sid,
        "X-Trace-Id": tid,
    }
    key = _llm_api_key()
    if key and key != "not-needed":
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _repo_web_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def _build_citations(
    full_name: str,
    readme: str,
    code_hits: list[dict[str, str]],
    *,
    readme_label: str | None = None,
) -> list[dict[str, Any]]:
    """Numbered citations with GitHub repo/file links (for [1], [2] in answer)."""
    citations: list[dict[str, Any]] = []
    idx = 1
    if readme:
        label = readme_label or "README"
        citations.append(
            {
                "index": idx,
                "url": _repo_web_url(full_name),
                "label": label,
                "repo": full_name,
                "type": "repository",
            }
        )
        idx += 1
    seen_urls: set[str] = set()
    for hit in code_hits:
        repo = hit.get("repo") or full_name
        path = hit.get("path") or ""
        url = (hit.get("url") or "").strip()
        if not url and path:
            url = f"https://github.com/{repo}/blob/HEAD/{path}"
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        short = repo.split("/", 1)[-1] if "/" in repo else repo
        label = f"{short}/{path}" if path else path or url
        citations.append(
            {
                "index": idx,
                "url": url,
                "label": label,
                "repo": repo,
                "type": "code",
            }
        )
        idx += 1
    if not citations:
        citations.append(
            {
                "index": 1,
                "url": _repo_web_url(full_name),
                "label": full_name,
                "repo": full_name,
                "type": "repository",
            }
        )
    return citations


def _merge_citations(repo_blocks: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Renumber citation blocks from multiple repos into one global [1..n] list."""
    merged: list[dict[str, Any]] = []
    offset = 0
    for _full_name, block in repo_blocks:
        for c in block:
            merged.append({**c, "index": offset + int(c["index"])})
        offset = len(merged)
    return merged


def _format_sources_for_llm(citations: list[dict[str, Any]], readme: str, code_hits: list[dict[str, str]]) -> str:
    lines = ["## Sources (use [n] in answer)"]
    for c in citations:
        lines.append(f"[{c['index']}] {c.get('label', '')} — {c['url']}")
    if readme:
        lines.append(f"\n## README excerpt\n{readme[:LLM_CONTEXT_README_MAX]}")
    if code_hits:
        lines.append("\n## Code snippets")
        for hit in code_hits:
            repo = hit.get("repo") or ""
            prefix = f"{repo}/" if repo else ""
            lines.append(
                f"### {prefix}{hit.get('path', '')}\n{hit.get('snippet') or '(no snippet)'}"
            )
    return "\n".join(lines)


def _format_multi_repo_sources(
    citations: list[dict[str, Any]],
    readmes: dict[str, str],
    code_hits: list[dict[str, str]],
) -> str:
    lines = ["## Sources (use [n] in answer)"]
    for c in citations:
        lines.append(f"[{c['index']}] {c.get('label', '')} — {c['url']}")
    if readmes:
        lines.append("\n## README excerpts")
        for full_name, text in readmes.items():
            if text:
                lines.append(f"\n### {full_name}\n{text[:_MULTI_REPO_README_MAX]}")
    if code_hits:
        lines.append("\n## Code snippets")
        for hit in code_hits:
            repo = hit.get("repo") or ""
            lines.append(
                f"### {repo}/{hit.get('path', '')}\n{hit.get('snippet') or '(no snippet)'}"
            )
    return "\n".join(lines)


def _conversation_id(scope: str, conversation_id: str | None) -> str:
    conv = (conversation_id or os.environ.get("LLM_CONVERSATION_ID") or "").strip()
    return conv or f"github-{scope.replace('/', '-')}"


def _usage_block(data: dict[str, Any]) -> dict[str, int]:
    u = data.get("usage") or {}
    return {
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "total_tokens": int(u.get("total_tokens") or 0),
    }


def _chat_completion(
    client: httpx.Client,
    *,
    messages: list[dict[str, str]],
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, int]]:
    base = _llm_gateway_base()
    if not base:
        raise ValueError("LLM_GATEWAY_BASE_URL not set in .env")

    payload = {
        "model": _llm_model(),
        "conversation_id": conversation_id,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else _llm_max_tokens(),
        "temperature": _llm_temperature(),
    }
    headers = _llm_headers(request_id=request_id, session_id=session_id, trace_id=trace_id)
    r = client.post(f"{base}/v1/chat/completions", json=payload, headers=headers, timeout=90.0)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    return content.strip(), _usage_block(data)


def _parse_openai_sse_chunk(line: str) -> tuple[str | None, dict[str, int] | None]:
    """Parse one SSE line; return (delta text, usage if present)."""
    if not line.startswith("data:"):
        return None, None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None, None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, None
    usage = data.get("usage")
    usage_out = _usage_block(data) if usage else None
    choices = data.get("choices") or []
    if not choices:
        return None, usage_out
    delta = (choices[0].get("delta") or {}).get("content")
    if delta is None:
        msg = choices[0].get("message") or {}
        delta = msg.get("content")
    if delta:
        return str(delta), usage_out
    return None, usage_out


def _iter_chat_completion_stream(
    client: httpx.Client,
    *,
    messages: list[dict[str, str]],
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    max_tokens: int | None = None,
) -> Iterator[tuple[str, Any]]:
    """Yield ('delta', str) then ('usage', dict) then ('done', full_text)."""
    base = _llm_gateway_base()
    if not base:
        raise ValueError("LLM_GATEWAY_BASE_URL not set in .env")

    payload = {
        "model": _llm_model(),
        "conversation_id": conversation_id,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else _llm_max_tokens(),
        "temperature": _llm_temperature(),
        "stream": True,
    }
    headers = _llm_headers(request_id=request_id, session_id=session_id, trace_id=trace_id)
    headers["Accept"] = "text/event-stream"
    parts: list[str] = []
    usage: dict[str, int] = {}

    with client.stream(
        "POST",
        f"{base}/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(30.0, read=180.0),
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = raw_line or ""
            text, usage_chunk = _parse_openai_sse_chunk(line)
            if usage_chunk and usage_chunk.get("total_tokens"):
                usage = usage_chunk
            if text:
                parts.append(text)
                yield ("delta", text)

    content = "".join(parts).strip()
    if not content:
        raise ValueError("LLM stream returned no content")
    if usage:
        yield ("usage", usage)
    yield ("done", content)


def _chat_completion_stream(
    client: httpx.Client,
    *,
    messages: list[dict[str, str]],
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    max_tokens: int | None = None,
    on_token: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, int]]:
    usage: dict[str, int] = {}
    answer = ""
    for kind, payload in _iter_chat_completion_stream(
        client,
        messages=messages,
        conversation_id=conversation_id,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        max_tokens=max_tokens,
    ):
        if kind == "delta":
            if on_token:
                on_token(str(payload))
        elif kind == "usage":
            usage = payload
        elif kind == "done":
            answer = str(payload)
    return answer, usage


def _generate_follow_ups(
    client: httpx.Client,
    question: str,
    answer: str,
    scope_label: str,
    *,
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
) -> tuple[list[str], dict[str, int]]:
    follow_max = int(os.environ.get("LLM_FOLLOW_UP_MAX_TOKENS", "256"))
    content, usage = _chat_completion(
        client,
        messages=[
            {"role": "system", "content": _FOLLOW_UP_PROMPT},
            {
                "role": "user",
                "content": f"Repositories: {scope_label}\nQuestion: {question}\nAnswer: {answer}",
            },
        ],
        conversation_id=conversation_id,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        max_tokens=follow_max,
    )
    try:
        parsed = json.loads(content)
        items = parsed.get("follow_up_questions") or []
        if isinstance(items, list):
            return [str(x).strip() for x in items if str(x).strip()][:3], usage
    except json.JSONDecodeError:
        pass
    return [], usage


def _fail(error: str, repo: str = "", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error, "allowed": _allowed_short_names()}
    if repo:
        out["repo"] = repo
    out.update(extra)
    return out


def resolve_repo(repo: str) -> dict[str, Any]:
    """Validate repo against tmp.md; return {ok, full_name} or error dict."""
    allowed = _allowed_short_names()
    if not allowed:
        return _fail("allowlist file tmp.md missing or empty")

    owner = _github_owner()
    if not owner:
        return _fail("GITHUB_OWNER not set in .env")

    raw = (repo or "").strip()
    if not raw:
        return _fail("repo is required", repo=raw)

    return _resolve_single_repo(raw, allowed, owner)


def _resolve_single_repo(raw: str, allowed: list[str], owner: str) -> dict[str, Any]:
    if "/" in raw:
        parts = raw.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return _fail("invalid owner/name format", repo=raw)
        repo_owner, short = parts[0], parts[1]
        if repo_owner != owner:
            return _fail(
                f"owner must be {owner} (got {repo_owner})",
                repo=raw,
            )
        if short not in allowed:
            return _fail("repo not allowed", repo=raw)
        return {"ok": True, "full_name": f"{owner}/{short}", "short": short}

    if raw not in allowed:
        return _fail("repo not allowed", repo=raw)
    return {"ok": True, "full_name": f"{owner}/{raw}", "short": raw}


def resolve_repos(repo: str | None = None) -> dict[str, Any]:
    """Resolve one repo or all allowlisted repos when repo is omitted."""
    allowed = _allowed_short_names()
    if not allowed:
        return _fail("allowlist file tmp.md missing or empty")

    owner = _github_owner()
    if not owner:
        return _fail("GITHUB_OWNER not set in .env")

    raw = (repo or "").strip()
    if not raw:
        return {
            "ok": True,
            "full_names": [f"{owner}/{short}" for short in allowed],
            "shorts": allowed,
            "scope": "all",
        }

    one = resolve_repo(raw)
    if not one.get("ok"):
        return one
    return {
        "ok": True,
        "full_names": [one["full_name"]],
        "shorts": [one["short"]],
        "scope": one["full_name"],
    }


def _search_keywords(question: str) -> str:
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", question or "")
    if words:
        return " ".join(words[:4])
    # fallback: strip to alnum-ish tokens for code search
    cleaned = re.sub(r"[^\w\s-]", " ", question or "")
    parts = [p for p in cleaned.split() if len(p) >= 2][:3]
    return " ".join(parts) if parts else "main"


def _gh_headers() -> dict[str, str]:
    token = _github_token()
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch_readme(client: httpx.Client, full_name: str) -> str:
    owner, name = full_name.split("/", 1)
    r = client.get(f"https://api.github.com/repos/{owner}/{name}/readme", headers=_gh_headers())
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    data = r.json()
    content = data.get("content") or ""
    encoding = data.get("encoding") or "base64"
    if encoding == "base64" and content:
        raw = base64.b64decode(content).decode("utf-8", errors="replace")
        return raw[:README_MAX]
    return ""


def _fetch_code_hits(client: httpx.Client, full_name: str, question: str) -> list[dict[str, str]]:
    return _fetch_code_hits_multi(client, [full_name], question, per_page=CODE_HITS_MAX)


def _fetch_code_hits_multi(
    client: httpx.Client,
    full_names: list[str],
    question: str,
    *,
    per_page: int = CODE_HITS_MAX,
) -> list[dict[str, str]]:
    if not full_names:
        return []
    kw = _search_keywords(question)
    if len(full_names) == 1:
        q = f"{kw} repo:{full_names[0]}"
        r = client.get(
            "https://api.github.com/search/code",
            params={"q": q, "per_page": per_page},
            headers={**_gh_headers(), "Accept": "application/vnd.github.text-match+json"},
        )
        if r.status_code in (403, 422):
            return []
        r.raise_for_status()
        items = r.json().get("items") or []
    else:
        # GitHub often 422 on long multi-repo OR queries — search per repo
        items = []
        seen_urls: set[str] = set()
        per_repo = max(3, per_page // len(full_names))
        for fn in full_names:
            q = f"{kw} repo:{fn}"
            r = client.get(
                "https://api.github.com/search/code",
                params={"q": q, "per_page": per_repo},
                headers={**_gh_headers(), "Accept": "application/vnd.github.text-match+json"},
            )
            if r.status_code in (403, 422):
                continue
            r.raise_for_status()
            for item in r.json().get("items") or []:
                url = item.get("html_url") or ""
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                items.append(item)
                if len(items) >= per_page:
                    break
            if len(items) >= per_page:
                break

    hits = []
    for item in items[:per_page]:
        path = item.get("path") or ""
        repo_full = (item.get("repository") or {}).get("full_name") or full_names[0]
        snippet = ""
        for tm in item.get("text_matches") or []:
            frag = tm.get("fragment") or ""
            if frag:
                snippet = frag.strip()[:SNIPPET_MAX]
                break
        hits.append(
            {
                "path": path,
                "url": item.get("html_url") or "",
                "snippet": snippet,
                "repo": repo_full,
            }
        )
    return hits


def _gather_github_evidence(
    client: httpx.Client,
    full_names: list[str],
    question: str,
    multi: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    """Fetch READMEs + code hits; return citations, LLM user_body, partial latency."""
    latency: dict[str, int] = {}
    scope_label = ", ".join(full_names)

    t_gh = time.perf_counter()
    readmes: dict[str, str] = {}
    for fn in full_names:
        readmes[fn] = _fetch_readme(client, fn)
    latency["github_readme"] = int((time.perf_counter() - t_gh) * 1000)

    t_gh = time.perf_counter()
    per_page = _MULTI_REPO_CODE_HITS_MAX if multi else CODE_HITS_MAX
    code_hits = _fetch_code_hits_multi(client, full_names, question, per_page=per_page)
    latency["github_search"] = int((time.perf_counter() - t_gh) * 1000)

    if multi:
        blocks: list[tuple[str, list[dict[str, Any]]]] = []
        for fn in full_names:
            short = fn.split("/", 1)[-1]
            repo_readme = readmes.get(fn) or ""
            repo_hits = [h for h in code_hits if h.get("repo") == fn]
            blocks.append(
                (
                    fn,
                    _build_citations(
                        fn,
                        repo_readme,
                        repo_hits,
                        readme_label=f"{short} README",
                    ),
                )
            )
        citations = _merge_citations(blocks)
        user_body = (
            f"Repositories ({len(full_names)} allowlisted): {scope_label}\n"
            f"User question: {question}\n\n"
            f"{_format_multi_repo_sources(citations, readmes, code_hits)}"
        )
    else:
        full_name = full_names[0]
        readme = readmes[full_name]
        citations = _build_citations(full_name, readme, code_hits)
        user_body = (
            f"Repository: {full_name}\nUser question: {question}\n\n"
            f"{_format_sources_for_llm(citations, readme, code_hits)}"
        )

    return citations, user_body, latency


def _finish_ask_repo_result(
    *,
    full_names: list[str],
    citations: list[dict[str, Any]],
    answer: str,
    follow_ups: list[str],
    latency: dict[str, int],
    chat_usage: dict[str, int],
    follow_usage: dict[str, int],
    rid: str,
    sid: str,
    tid: str,
    conv: str,
    t0: float,
) -> dict[str, Any]:
    latency["total"] = int((time.perf_counter() - t0) * 1000)
    usage_out: dict[str, Any] = {"chat": chat_usage}
    if follow_usage.get("total_tokens"):
        usage_out["follow_up_chat"] = follow_usage
    usage_out["total"] = {
        "prompt_tokens": chat_usage.get("prompt_tokens", 0) + follow_usage.get("prompt_tokens", 0),
        "completion_tokens": chat_usage.get("completion_tokens", 0) + follow_usage.get("completion_tokens", 0),
        "total_tokens": chat_usage.get("total_tokens", 0) + follow_usage.get("total_tokens", 0),
    }
    out: dict[str, Any] = {
        "ok": True,
        "repos": full_names,
        "answer": answer,
        "citations": citations,
        "follow_up_questions": follow_ups,
        "latency_ms": latency,
        "usage": usage_out,
        "request_id": rid,
        "session_id": sid,
        "trace_id": tid,
        "conversation_id": conv,
    }
    if len(full_names) == 1:
        out["repo"] = full_names[0]
    return out


def _ask_repo_impl(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_repos(repo)
    if not resolved.get("ok"):
        return resolved

    token = _github_token()
    if not token:
        return _fail("GITHUB_TOKEN not set in .env", repo=repo or "")

    full_names: list[str] = resolved["full_names"]
    scope = resolved["scope"]
    multi = len(full_names) > 1

    if not _llm_gateway_base():
        return _fail("LLM_GATEWAY_BASE_URL not set in .env (required to synthesize answers)", repo=repo or "")

    rid = (request_id or os.environ.get("LLM_REQUEST_ID") or "").strip() or str(uuid.uuid4())
    sid = (session_id or os.environ.get("LLM_SESSION_ID") or "").strip() or "layer-mcp-github"
    tid = (trace_id or os.environ.get("LLM_TRACE_ID") or "").strip() or rid
    conv = _conversation_id(scope, conversation_id)

    t0 = time.perf_counter()
    latency: dict[str, int] = {}
    chat_usage: dict[str, int] = {}
    follow_usage: dict[str, int] = {}
    scope_label = ", ".join(full_names)

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            citations, user_body, gh_latency = _gather_github_evidence(
                client, full_names, question, multi
            )
            latency.update(gh_latency)

            t_llm = time.perf_counter()
            answer, chat_usage = _chat_completion(
                client,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_body},
                ],
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
            )
            latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

            t_llm = time.perf_counter()
            follow_ups, follow_usage = _generate_follow_ups(
                client,
                question,
                answer,
                scope_label,
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
            )
            latency["follow_up_chat"] = int((time.perf_counter() - t_llm) * 1000)

    except httpx.HTTPStatusError as e:
        return _fail(f"GitHub API error: {e.response.status_code}", repo=repo or "")
    except httpx.HTTPError as e:
        return _fail(f"Request failed: {e}", repo=repo or "")
    except ValueError as e:
        return _fail(str(e), repo=repo or "")

    return _finish_ask_repo_result(
        full_names=full_names,
        citations=citations,
        answer=answer,
        follow_ups=follow_ups,
        latency=latency,
        chat_usage=chat_usage,
        follow_usage=follow_usage,
        rid=rid,
        sid=sid,
        tid=tid,
        conv=conv,
        t0=t0,
    )


def _sse_format(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_ask_repo_events(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str, dict[str, Any]], None] | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames: status → answer_delta → done (or error)."""
    resolved = resolve_repos(repo)
    if not resolved.get("ok"):
        yield _sse_format("error", resolved)
        return

    token = _github_token()
    if not token:
        yield _sse_format("error", _fail("GITHUB_TOKEN not set in .env", repo=repo or ""))
        return

    if not _llm_gateway_base():
        yield _sse_format(
            "error",
            _fail("LLM_GATEWAY_BASE_URL not set in .env (required to synthesize answers)", repo=repo or ""),
        )
        return

    full_names: list[str] = resolved["full_names"]
    scope = resolved["scope"]
    multi = len(full_names) > 1
    rid = (request_id or os.environ.get("LLM_REQUEST_ID") or "").strip() or str(uuid.uuid4())
    sid = (session_id or os.environ.get("LLM_SESSION_ID") or "").strip() or "layer-mcp-github"
    tid = (trace_id or os.environ.get("LLM_TRACE_ID") or "").strip() or rid
    conv = _conversation_id(scope, conversation_id)
    scope_label = ", ".join(full_names)
    t0 = time.perf_counter()
    latency: dict[str, int] = {}
    chat_usage: dict[str, int] = {}
    follow_usage: dict[str, int] = {}

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as client:
            yield _sse_format("status", {"phase": "github_readme", "repos": full_names})
            if on_status:
                on_status("github_readme", {"repos": full_names})

            citations, user_body, gh_latency = _gather_github_evidence(
                client, full_names, question, multi
            )
            latency.update(gh_latency)
            yield _sse_format(
                "status",
                {
                    "phase": "github_done",
                    "latency_ms": gh_latency,
                    "citation_count": len(citations),
                },
            )

            yield _sse_format("status", {"phase": "chat_stream"})
            t_llm = time.perf_counter()
            answer = ""
            chat_usage: dict[str, int] = {}
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_body},
            ]
            for kind, payload in _iter_chat_completion_stream(
                client,
                messages=messages,
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
            ):
                if kind == "delta":
                    text = str(payload)
                    if on_token:
                        on_token(text)
                    yield _sse_format("answer_delta", {"text": text})
                elif kind == "usage":
                    chat_usage = payload
                elif kind == "done":
                    answer = str(payload)

            latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

            yield _sse_format("status", {"phase": "follow_up_chat"})
            t_llm = time.perf_counter()
            follow_ups, follow_usage = _generate_follow_ups(
                client,
                question,
                answer,
                scope_label,
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
            )
            latency["follow_up_chat"] = int((time.perf_counter() - t_llm) * 1000)

    except httpx.HTTPStatusError as e:
        yield _sse_format("error", {"ok": False, "error": f"GitHub API error: {e.response.status_code}"})
        return
    except httpx.HTTPError as e:
        yield _sse_format("error", {"ok": False, "error": f"Request failed: {e}"})
        return
    except ValueError as e:
        yield _sse_format("error", {"ok": False, "error": str(e)})
        return

    result = _finish_ask_repo_result(
        full_names=full_names,
        citations=citations,
        answer=answer,
        follow_ups=follow_ups,
        latency=latency,
        chat_usage=chat_usage,
        follow_usage=follow_usage,
        rid=rid,
        sid=sid,
        tid=tid,
        conv=conv,
        t0=t0,
    )
    yield _sse_format("done", result)



@mcp.tool()
def ask_repo(
    question: str,
    repo: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Answer a question about allowlisted GitHub repos (retrieve + LLM synthesis).

    Default (no repo): search all repos in tmp.md (layer-web-v1, layer-orchestrator-v1, k3s, etc.).
    Optional repo: short name or owner/name matching GITHUB_OWNER.

    Fetches READMEs and code search from GitHub, then POSTs to LLM_GATEWAY_BASE_URL/v1/chat/completions.

    Returns RAG-style payload: repos, answer (with [n] cites), citations, follow_up_questions,
    latency_ms, usage, request_id, session_id, trace_id, conversation_id.
    """
    return _ask_repo_impl(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
    )


@mcp.tool()
async def ask_repo_stream(
    question: str,
    repo: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Like ask_repo but streams LLM answer tokens via MCP logs/progress, then returns full payload.

    Default (no repo): all tmp.md repos. Emits JSON log lines: answer_delta, then final done object.
    """
    final: dict[str, Any] = {"ok": False, "error": "stream ended without result"}
    step = 0
    total_steps = 6

    async for frame in _stream_ask_repo_events(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
    ):
        event = ""
        data: dict[str, Any] = {}
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    data = {}

        if ctx:
            if event == "status":
                step += 1
                await ctx.report_progress(step, total_steps, data.get("phase", ""))
            elif event == "answer_delta":
                text = data.get("text") or ""
                if text:
                    await ctx.info(json.dumps({"type": "answer_delta", "text": text}))
            elif event == "error":
                await ctx.error(data.get("error", "stream error"))
                return data

        if event == "done":
            final = data
        elif event == "error":
            return data

    return final


@mcp.custom_route("/ask/stream", methods=["POST"])
async def http_ask_stream(request: Request) -> Response:
    """SSE stream: status → answer_delta → done. Body JSON: { question, repo?, request_id?, ... }."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON body"}, status_code=400)

    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"ok": False, "error": "question is required"}, status_code=400)

    async def event_gen() -> AsyncIterator[str]:
        async for chunk in _stream_ask_repo_events(
            body.get("repo"),
            question,
            request_id=body.get("request_id"),
            session_id=body.get("session_id"),
            trace_id=body.get("trace_id"),
            conversation_id=body.get("conversation_id"),
        ):
            yield chunk

    return StreamingResponse(event_gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        llm = _llm_gateway_base() or "(not set — ask_repo will fail)"
        default_repos = _allowed_short_names()
        print(f"MCP HTTP http://127.0.0.1:{_HTTP_PORT}/mcp  (no trailing slash for curl)", flush=True)
        print(f"Stream SSE POST http://127.0.0.1:{_HTTP_PORT}/ask/stream", flush=True)
        print(f"LLM gateway: {llm}", flush=True)
        print(f"Default repos ({len(default_repos)}): {', '.join(default_repos)}", flush=True)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
