"""Ask-repo pipeline: GitHub evidence, LLM answer, follow-ups."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.allowlist import fail, resolve_repos
from app.citations import (
    build_citations,
    format_multi_repo_sources,
    format_sources_for_llm,
    merge_citations,
)
from app.config import (
    CODE_HITS_MAX,
    MULTI_REPO_CODE_HITS_MAX,
    SYSTEM_PROMPT,
)
from app.github_client import fetch_code_hits_multi, fetch_readme, github_token
from app.correlation import UserContext, resolve_correlation
from app.llm import chat_completion, generate_follow_ups, llm_gateway_base


def gather_github_evidence(
    client: httpx.Client,
    full_names: list[str],
    question: str,
    multi: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, int]]:
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


def ask_repo_impl(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    user: UserContext | None = None,
) -> dict[str, Any]:
    resolved = resolve_repos(repo)
    if not resolved.get("ok"):
        return resolved

    if not github_token():
        return fail("GITHUB_TOKEN not set in .env", repo=repo or "")

    full_names: list[str] = resolved["full_names"]
    scope = resolved["scope"]
    multi = len(full_names) > 1

    if not llm_gateway_base():
        return fail(
            "LLM_GATEWAY_BASE_URL not set in .env (required to synthesize answers)",
            repo=repo or "",
        )

    rid, sid, tid, conv = resolve_correlation(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id_arg,
    )

    t0 = time.perf_counter()
    latency: dict[str, int] = {}
    chat_usage: dict[str, int] = {}
    follow_usage: dict[str, int] = {}
    scope_label = ", ".join(full_names)

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            citations, user_body, gh_latency = gather_github_evidence(
                client, full_names, question, multi
            )
            latency.update(gh_latency)

            t_llm = time.perf_counter()
            answer, chat_usage = chat_completion(
                client,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_body},
                ],
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
                user=user,
            )
            latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

            t_llm = time.perf_counter()
            follow_ups, follow_usage = generate_follow_ups(
                client,
                question,
                answer,
                scope_label,
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
                user=user,
            )
            latency["follow_up_chat"] = int((time.perf_counter() - t_llm) * 1000)

    except httpx.HTTPStatusError as e:
        return fail(f"GitHub API error: {e.response.status_code}", repo=repo or "")
    except httpx.HTTPError as e:
        return fail(f"Request failed: {e}", repo=repo or "")
    except ValueError as e:
        return fail(str(e), repo=repo or "")

    return finish_ask_repo_result(
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
