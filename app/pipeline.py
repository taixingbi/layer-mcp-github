"""Ask-repo pipeline: GitHub evidence, LLM answer, follow-ups."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ask_common import (
    error_payload,
    httpx_error_message,
    log_ask_done,
    log_ask_exception,
    log_ask_fail,
    log_ask_github_done,
    log_ask_start,
    resolve_ask_scope,
    run_buffered_llm,
    service_prereq_error,
)
from app.citations import (
    build_citations,
    format_multi_repo_sources,
    format_sources_for_llm,
    merge_citations,
)
from app.config import CODE_HITS_MAX, MULTI_REPO_CODE_HITS_MAX
from app.correlation import UserContext, resolve_correlation
from app.github_client import fetch_code_hits_multi, fetch_readme
from app.log_context import bind_ask_context


def gather_github_evidence(
    client: httpx.Client,
    full_names: list[str],
    question: str,
    multi: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
    """Fetch READMEs and code search hits; build citations and LLM user message body."""
    latency: dict[str, int] = {}
    scope_label = ", ".join(full_names)

    t_gh = time.perf_counter()
    readmes: dict[str, str] = {}
    for fn in full_names:
        readmes[fn] = fetch_readme(client, fn)
    latency["github_readme"] = int((time.perf_counter() - t_gh) * 1000)

    t_gh = time.perf_counter()
    per_page = MULTI_REPO_CODE_HITS_MAX if multi else CODE_HITS_MAX
    code_hits = fetch_code_hits_multi(client, full_names, question, per_page=per_page)
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
                    build_citations(
                        fn,
                        repo_readme,
                        repo_hits,
                        readme_label=f"{short} README",
                    ),
                )
            )
        citations = merge_citations(blocks)
        user_body = (
            f"Repositories ({len(full_names)} allowlisted): {scope_label}\n"
            f"User question: {question}\n\n"
            f"{format_multi_repo_sources(citations, readmes, code_hits)}"
        )
    else:
        full_name = full_names[0]
        readme = readmes[full_name]
        citations = build_citations(full_name, readme, code_hits)
        user_body = (
            f"Repository: {full_name}\nUser question: {question}\n\n"
            f"{format_sources_for_llm(citations, readme, code_hits)}"
        )

    return citations, user_body, latency


def finish_ask_repo_result(
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
    tid: str | None,
    conv: str,
    t0: float,
) -> dict[str, Any]:
    """Assemble the RAG-style JSON payload returned by ask_repo tools."""
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


def ask_repo_impl(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    user: UserContext | None = None,
    http_method: str = "-",
    http_path: str = "-",
    stream: bool = False,
    tool_name: str = "ask_repo",
) -> dict[str, Any]:
    """Buffered ask_repo: GitHub retrieval, gateway chat, follow-ups (sync, for MCP thread pool)."""
    rid, sid, tid, conv = resolve_correlation(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id_arg,
    )

    def _fail(msg: str, **extra: Any) -> dict[str, Any]:
        log_ask_fail(msg, tool_name=tool_name, stream=stream, **extra)
        return error_payload(msg, repo, request_id=rid, session_id=sid, trace_id=tid, conversation_id=conv)

    with bind_ask_context(
        request_id=rid,
        session_id=sid,
        trace_id=tid,
        conversation_id=conv,
        user=user,
        method=http_method,
        path=http_path,
    ):
        scope, err = resolve_ask_scope(repo)
        if err is not None:
            return _fail(err.get("error", "resolve failed"))

        prereq = service_prereq_error()
        if prereq:
            return _fail(prereq)

        assert scope is not None
        log_ask_start(scope, tool_name=tool_name, stream=stream, user=user)
        t0 = time.perf_counter()
        latency: dict[str, int] = {}

        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
                citations, user_body, gh_latency = gather_github_evidence(
                    client, scope.full_names, question, scope.multi
                )
                latency.update(gh_latency)
                log_ask_github_done(len(citations), gh_latency, stream=stream)

                answer, follow_ups, llm_latency, chat_usage, follow_usage = run_buffered_llm(
                    client,
                    question=question,
                    user_body=user_body,
                    scope_label=scope.scope_label,
                    conversation_id=conv,
                    request_id=rid,
                    session_id=sid,
                    trace_id=tid,
                    user=user,
                )
                latency.update(llm_latency)

        except (httpx.HTTPError, ValueError) as e:
            log_ask_exception(e, stream=stream)
            extra = (
                {"upstream_status": e.response.status_code}
                if isinstance(e, httpx.HTTPStatusError)
                else {}
            )
            return _fail(httpx_error_message(e), **extra)

        result = finish_ask_repo_result(
            full_names=scope.full_names,
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
        log_ask_done(
            scope,
            tool_name=tool_name,
            stream=stream,
            user=user,
            citation_count=len(citations),
            follow_up_count=len(follow_ups),
            latency_ms=result["latency_ms"],
        )
        return result
