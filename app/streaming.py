"""SSE streaming and MCP stream consumer."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from mcp.server.fastmcp import Context

from app.allowlist import fail, resolve_repos
from app.config import SYSTEM_PROMPT
from app.github_client import github_token
from app.correlation import UserContext, meta_event_payload, resolve_correlation
from app.llm import generate_follow_ups, iter_chat_completion_stream, llm_gateway_base
from app.pipeline import finish_ask_repo_result, gather_github_evidence


def sse_format(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_ask_repo_events(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    user: UserContext | None = None,
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str, dict[str, Any]], None] | None = None,
) -> AsyncIterator[str]:
    resolved = resolve_repos(repo)
    if not resolved.get("ok"):
        yield sse_format("error", resolved)
        return

    if not github_token():
        yield sse_format("error", fail("GITHUB_TOKEN not set in .env", repo=repo or ""))
        return

    if not llm_gateway_base():
        yield sse_format(
            "error",
            fail(
                "LLM_GATEWAY_BASE_URL not set in .env (required to synthesize answers)",
                repo=repo or "",
            ),
        )
        return

    full_names: list[str] = resolved["full_names"]
    scope = resolved["scope"]
    multi = len(full_names) > 1
    rid, sid, tid, conv = resolve_correlation(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id_arg,
    )
    scope_label = ", ".join(full_names)
    t0 = time.perf_counter()

    yield sse_format(
        "meta",
        meta_event_payload(
            rid,
            sid,
            tid,
            conv,
            repos=full_names,
            repo=full_names[0] if len(full_names) == 1 else None,
            user=user,
        ),
    )
    latency: dict[str, int] = {}
    chat_usage: dict[str, int] = {}
    follow_usage: dict[str, int] = {}
    citations: list[dict[str, Any]] = []
    answer = ""
    follow_ups: list[str] = []

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=180.0)) as client:
            yield sse_format("status", {"phase": "github_readme", "repos": full_names})
            if on_status:
                on_status("github_readme", {"repos": full_names})

            citations, user_body, gh_latency = gather_github_evidence(
                client, full_names, question, multi
            )
            latency.update(gh_latency)
            yield sse_format(
                "status",
                {
                    "phase": "github_done",
                    "latency_ms": gh_latency,
                    "citation_count": len(citations),
                },
            )

            yield sse_format("status", {"phase": "chat_stream"})
            t_llm = time.perf_counter()
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_body},
            ]
            for kind, payload in iter_chat_completion_stream(
                client,
                messages=messages,
                conversation_id=conv,
                request_id=rid,
                session_id=sid,
                trace_id=tid,
                user=user,
            ):
                if kind == "delta":
                    text = str(payload)
                    if on_token:
                        on_token(text)
                    yield sse_format("answer_delta", {"text": text})
                elif kind == "usage":
                    chat_usage = payload
                elif kind == "done":
                    answer = str(payload)

            latency["chat"] = int((time.perf_counter() - t_llm) * 1000)

            yield sse_format("status", {"phase": "follow_up_chat"})
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
        yield sse_format("error", {"ok": False, "error": f"GitHub API error: {e.response.status_code}"})
        return
    except httpx.HTTPError as e:
        yield sse_format("error", {"ok": False, "error": f"Request failed: {e}"})
        return
    except ValueError as e:
        yield sse_format("error", {"ok": False, "error": str(e)})
        return

    result = finish_ask_repo_result(
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
    yield sse_format("done", result)


async def ask_repo_mcp_stream(
    repo: str | None,
    question: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    conversation_id_arg: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    final: dict[str, Any] = {"ok": False, "error": "stream ended without result"}
    step = 0
    total_steps = 6

    async for frame in stream_ask_repo_events(
        repo,
        question,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id_arg=conversation_id_arg,
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
