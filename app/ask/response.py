"""Standard ask_repo tool response shape (buffered and stream ``done``)."""

from __future__ import annotations

from typing import Any

from app.config import SNIPPET_MAX
from app.observability.correlation import UserContext

TOOL_API_VERSION = "v1"
TOOL_TYPE = "github"
GITHUB_SEARCH_TOOL = "github_search"


def tool_metrics_key(logical_tool: str) -> str:
    """Prefix for per-tool ``latency_ms`` / ``usage`` blocks (e.g. ``tool_github_search``)."""
    return f"tool_{logical_tool}"


def _user_meta(user: UserContext | None) -> dict[str, str]:
    if user is None:
        return {"id": "-", "roles": "", "groups": "", "teams": ""}
    return {
        "id": user.user_id,
        "roles": user.user_roles,
        "groups": user.user_groups,
        "teams": user.user_teams,
    }


def build_route(scope_label: str, *, logical_tool: str = GITHUB_SEARCH_TOOL) -> dict[str, Any]:
    """Deterministic tool route placed under ``meta.route``."""
    return {
        "type": "tool",
        "tool": logical_tool,
        "confidence": 0.99,
        "reason": f"Deterministic: {scope_label} question",
        "source": "deterministic_rule",
    }


def build_meta(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None = None,
    repos: list[str] | None = None,
    repo: str | None = None,
    scope: str | None = None,
    scope_label: str | None = None,
    question: str | None = None,
    is_new_conversation: bool = False,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """``meta`` block for tool responses and stream ``meta`` events."""
    label = scope_label or scope or repo or logical_tool
    meta: dict[str, Any] = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "is_new_conversation": is_new_conversation,
        "user": _user_meta(user),
        "route": build_route(label, logical_tool=logical_tool),
        "tool": {
            "name": logical_tool,
            "type": TOOL_TYPE,
            "version": TOOL_API_VERSION,
        },
    }
    if question:
        meta["rewrite"] = question.strip()
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


def map_latency_ms(
    internal: dict[str, int],
    *,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """Nested ``latency_ms``: top-level ``total`` + ``tool_<name>`` breakdown."""
    readme = int(internal.get("github_readme") or 0)
    search = int(internal.get("github_search") or 0)
    breakdown: dict[str, int] = {}
    retrieve = readme + search
    if retrieve:
        breakdown["retrieve_rerank"] = retrieve
    if "chat" in internal:
        breakdown["chat"] = int(internal["chat"])
    if "follow_up_chat" in internal:
        breakdown["follow_up_chat"] = int(internal["follow_up_chat"])
    total = int(internal.get("total") or 0)
    if total:
        breakdown["total"] = total
    out: dict[str, Any] = {}
    if total:
        out["total"] = total
    if breakdown:
        out[tool_metrics_key(logical_tool)] = breakdown
    return out


def map_usage_block(
    chat_usage: dict[str, int],
    follow_usage: dict[str, int],
    *,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """Nested ``usage``: top-level ``total`` + ``tool_<name>`` with chat / follow_up_chat."""
    total = {
        "prompt_tokens": chat_usage.get("prompt_tokens", 0) + follow_usage.get("prompt_tokens", 0),
        "completion_tokens": chat_usage.get("completion_tokens", 0)
        + follow_usage.get("completion_tokens", 0),
        "total_tokens": chat_usage.get("total_tokens", 0) + follow_usage.get("total_tokens", 0),
    }
    tool_block: dict[str, Any] = {"total": dict(total)}
    if chat_usage.get("total_tokens"):
        tool_block["chat"] = dict(chat_usage)
    if follow_usage.get("total_tokens"):
        tool_block["follow_up_chat"] = dict(follow_usage)
    return {"total": total, tool_metrics_key(logical_tool): tool_block}


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


def _status_ok() -> dict[str, Any]:
    return {"ok": True, "state": "completed", "code": "ok"}


def _status_failed(message: str) -> dict[str, Any]:
    return {"ok": False, "state": "failed", "code": "failed", "message": message}


def build_tool_response(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None,
    repos: list[str],
    scope: str,
    scope_label: str,
    question: str,
    is_new_conversation: bool,
    answer_text: str,
    internal_citations: list[dict[str, Any]],
    readmes: dict[str, str],
    code_hits: list[dict[str, str]],
    follow_up_questions: list[str],
    internal_latency: dict[str, int],
    chat_usage: dict[str, int],
    follow_usage: dict[str, int],
    stream_done: bool = False,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """Full tool result (buffered ``structuredContent`` or stream ``done`` event)."""
    repo = repos[0] if len(repos) == 1 else None
    body: dict[str, Any] = {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            user=user,
            repos=repos,
            repo=repo,
            scope=scope,
            scope_label=scope_label,
            question=question,
            is_new_conversation=is_new_conversation,
            logical_tool=logical_tool,
        ),
        "answer": {
            "text": answer_text,
            "citations": citations_for_answer(internal_citations, readmes, code_hits),
        },
        "follow_up_questions": list(follow_up_questions),
        "latency_ms": map_latency_ms(internal_latency, logical_tool=logical_tool),
        "usage": map_usage_block(chat_usage, follow_usage, logical_tool=logical_tool),
        "status": _status_ok(),
    }
    if stream_done:
        body["type"] = "done"
    return body


def build_tool_error(
    message: str,
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None = None,
    repo: str | None = None,
    allowed: list[str] | None = None,
    question: str | None = None,
    is_new_conversation: bool = False,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """Failed tool result (buffered or stream terminal)."""
    meta = build_meta(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        user=user,
        repo=repo,
        scope_label=repo or logical_tool,
        question=question,
        is_new_conversation=is_new_conversation,
        logical_tool=logical_tool,
    )
    if allowed is not None:
        meta.setdefault("github", {})["allowed"] = allowed
    return {
        "meta": meta,
        "answer": {"text": "", "citations": []},
        "follow_up_questions": [],
        "latency_ms": {},
        "usage": {},
        "status": _status_failed(message),
    }


def stream_meta_event(
    *,
    request_id: str,
    session_id: str,
    trace_id: str | None,
    conversation_id: str,
    user: UserContext | None,
    repos: list[str],
    scope: str,
    scope_label: str,
    question: str,
    is_new_conversation: bool,
    logical_tool: str = GITHUB_SEARCH_TOOL,
) -> dict[str, Any]:
    """SSE ``meta`` event body (meta only — no duplicate fields on ``delta`` / ``done``)."""
    repo = repos[0] if len(repos) == 1 else None
    return {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            user=user,
            repos=repos,
            repo=repo,
            scope=scope,
            scope_label=scope_label,
            question=question,
            is_new_conversation=is_new_conversation,
            logical_tool=logical_tool,
        ),
    }


def stream_delta_event(text: str) -> dict[str, Any]:
    """SSE ``delta`` event body (answer text chunk only)."""
    return {"answer": {"text": text}}
