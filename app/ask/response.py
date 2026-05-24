"""Standard ask_repo tool response shape (buffered and stream ``done``)."""

from __future__ import annotations

from typing import Any

from app.config import SNIPPET_MAX
from app.observability.correlation import UserContext
TOOL_API_VERSION = "v1"
TOOL_TYPE = "github"


def _user_meta(user: UserContext | None) -> dict[str, str]:
    if user is None:
        return {"id": "-", "roles": "", "groups": "", "teams": ""}
    return {
        "id": user.user_id,
        "roles": user.user_roles,
        "groups": user.user_groups,
        "teams": user.user_teams,
    }


def build_meta(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    tool_name: str,
    user: UserContext | None = None,
    repos: list[str] | None = None,
    repo: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """``meta`` block for tool responses and stream ``meta`` events."""
    meta: dict[str, Any] = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "user": _user_meta(user),
        "tool": {
            "name": tool_name,
            "type": TOOL_TYPE,
            "version": TOOL_API_VERSION,
        },
    }
    github: dict[str, Any] = {}
    if repos is not None:
        github["repos"] = repos
    if repo is not None:
        github["repo"] = repo
    if scope is not None:
        github["scope"] = scope
    if github:
        meta["github"] = github
    return meta


def map_latency_ms(internal: dict[str, int]) -> dict[str, int]:
    """Map internal github_* keys to standard ``latency_ms`` names."""
    readme = int(internal.get("github_readme") or 0)
    search = int(internal.get("github_search") or 0)
    out: dict[str, int] = {}
    retrieve = readme + search
    if retrieve:
        out["retrieve_rerank"] = retrieve
    if "chat" in internal:
        out["chat"] = int(internal["chat"])
    if "follow_up_chat" in internal:
        out["follow_up_chat"] = int(internal["follow_up_chat"])
    if "total" in internal:
        out["total"] = int(internal["total"])
    return out


def map_usage_block(
    chat_usage: dict[str, int],
    follow_usage: dict[str, int],
) -> dict[str, Any]:
    """``usage`` block with chat, optional follow_up_chat, and total."""
    usage: dict[str, Any] = {"chat": dict(chat_usage)}
    if follow_usage.get("total_tokens"):
        usage["follow_up_chat"] = dict(follow_usage)
    usage["total"] = {
        "prompt_tokens": chat_usage.get("prompt_tokens", 0) + follow_usage.get("prompt_tokens", 0),
        "completion_tokens": chat_usage.get("completion_tokens", 0)
        + follow_usage.get("completion_tokens", 0),
        "total_tokens": chat_usage.get("total_tokens", 0) + follow_usage.get("total_tokens", 0),
    }
    return usage


def citations_for_answer(
    internal: list[dict[str, Any]],
    readmes: dict[str, str],
    code_hits: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Map internal citation records to ``cite_id`` / ``source`` / ``text``."""
    hits_by_key: dict[tuple[str, str], str] = {}
    for hit in code_hits:
        repo = hit.get("repo") or ""
        path = hit.get("path") or ""
        snippet = (hit.get("snippet") or "").strip()
        if snippet:
            hits_by_key[(repo, path)] = snippet[:SNIPPET_MAX]

    out: list[dict[str, Any]] = []
    for c in internal:
        cite_id = int(c.get("index") or 0)
        repo = str(c.get("repo") or "")
        source = str(c.get("label") or c.get("url") or "")
        ctype = c.get("type") or ""
        text = ""
        if ctype == "repository":
            readme = (readmes.get(repo) or "").strip()
            text = readme[:SNIPPET_MAX] if readme else source
        else:
            path = ""
            if "/" in source and not source.startswith("http"):
                path = source.split("/", 1)[-1]
            text = hits_by_key.get((repo, path), "") or source
        out.append({"cite_id": cite_id, "source": source, "text": text})
    return out


def build_tool_response(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    tool_name: str,
    user: UserContext | None,
    repos: list[str],
    scope: str,
    answer_text: str,
    internal_citations: list[dict[str, Any]],
    readmes: dict[str, str],
    code_hits: list[dict[str, str]],
    follow_up_questions: list[str],
    internal_latency: dict[str, int],
    chat_usage: dict[str, int],
    follow_usage: dict[str, int],
) -> dict[str, Any]:
    """Full tool result (non-stream or stream ``done`` event)."""
    repo = repos[0] if len(repos) == 1 else None
    return {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            user=user,
            repos=repos,
            repo=repo,
            scope=scope,
        ),
        "answer": {
            "text": answer_text,
            "citations": citations_for_answer(internal_citations, readmes, code_hits),
        },
        "follow_up_questions": list(follow_up_questions),
        "latency_ms": map_latency_ms(internal_latency),
        "usage": map_usage_block(chat_usage, follow_usage),
        "status": {"ok": True, "state": "completed"},
    }


def build_tool_error(
    message: str,
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    tool_name: str,
    user: UserContext | None = None,
    repo: str | None = None,
    allowed: list[str] | None = None,
) -> dict[str, Any]:
    """Failed tool result (buffered or stream terminal)."""
    meta = build_meta(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        user=user,
        repo=repo,
    )
    if allowed is not None:
        meta.setdefault("github", {})["allowed"] = allowed
    return {
        "meta": meta,
        "answer": {"text": "", "citations": []},
        "follow_up_questions": [],
        "latency_ms": {},
        "usage": {},
        "status": {"ok": False, "state": "failed", "message": message},
    }


def stream_meta_event(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    tool_name: str,
    user: UserContext | None,
    repos: list[str],
    scope: str,
) -> dict[str, Any]:
    """SSE ``meta`` event body (meta only — no duplicate fields)."""
    repo = repos[0] if len(repos) == 1 else None
    return {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            user=user,
            repos=repos,
            repo=repo,
            scope=scope,
        ),
    }


def stream_delta_event(text: str) -> dict[str, Any]:
    """SSE ``delta`` event body (answer text chunk only)."""
    return {"answer": {"text": text}}
