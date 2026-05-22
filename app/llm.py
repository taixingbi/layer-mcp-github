"""LLM gateway: chat completions and streaming."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from app.config import FOLLOW_UP_PROMPT
from app.correlation import UserContext, user_header_values


def llm_gateway_base() -> str:
    return (os.environ.get("LLM_GATEWAY_BASE_URL") or "").strip().rstrip("/")


def llm_model() -> str:
    return (os.environ.get("LLM_MODEL") or "Qwen/Qwen2.5-7B-Instruct").strip()


def llm_api_key() -> str:
    return (os.environ.get("LLM_API_KEY") or "not-needed").strip()


def llm_max_tokens() -> int:
    return int(os.environ.get("LLM_MAX_TOKENS", "1024"))


def llm_temperature() -> float:
    return float(os.environ.get("LLM_TEMPERATURE", "0.7"))


def llm_headers(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    user: UserContext | None = None,
) -> dict[str, str]:
    rid = (request_id or os.environ.get("LLM_REQUEST_ID") or "").strip() or str(uuid.uuid4())
    sid = (session_id or os.environ.get("LLM_SESSION_ID") or "").strip() or str(uuid.uuid4())
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Request-Id": rid,
        "X-Session-Id": sid,
    }
    tid = (trace_id or os.environ.get("LLM_TRACE_ID") or "").strip()
    if tid:
        headers["X-Trace-Id"] = tid
    headers.update(user_header_values(user))
    key = llm_api_key()
    if key and key != "not-needed":
        headers["Authorization"] = f"Bearer {key}"
    return headers


def usage_block(data: dict[str, Any]) -> dict[str, int]:
    u = data.get("usage") or {}
    return {
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "total_tokens": int(u.get("total_tokens") or 0),
    }


def chat_completion(
    client: httpx.Client,
    *,
    messages: list[dict[str, str]],
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    max_tokens: int | None = None,
    user: UserContext | None = None,
) -> tuple[str, dict[str, int]]:
    base = llm_gateway_base()
    if not base:
        raise ValueError("LLM_GATEWAY_BASE_URL not set in .env")

    payload = {
        "model": llm_model(),
        "conversation_id": conversation_id,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else llm_max_tokens(),
        "temperature": llm_temperature(),
    }
    headers = llm_headers(
        request_id=request_id, session_id=session_id, trace_id=trace_id, user=user
    )
    r = client.post(f"{base}/v1/chat/completions", json=payload, headers=headers, timeout=90.0)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM returned no choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    return content.strip(), usage_block(data)


def parse_openai_sse_chunk(line: str) -> tuple[str | None, dict[str, int] | None]:
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
    usage_out = usage_block(data) if usage else None
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


def iter_chat_completion_stream(
    client: httpx.Client,
    *,
    messages: list[dict[str, str]],
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    max_tokens: int | None = None,
    user: UserContext | None = None,
) -> Iterator[tuple[str, Any]]:
    base = llm_gateway_base()
    if not base:
        raise ValueError("LLM_GATEWAY_BASE_URL not set in .env")

    payload = {
        "model": llm_model(),
        "conversation_id": conversation_id,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else llm_max_tokens(),
        "temperature": llm_temperature(),
        "stream": True,
    }
    headers = llm_headers(
        request_id=request_id, session_id=session_id, trace_id=trace_id, user=user
    )
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
            text, usage_chunk = parse_openai_sse_chunk(line)
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


def generate_follow_ups(
    client: httpx.Client,
    question: str,
    answer: str,
    scope_label: str,
    *,
    conversation_id: str,
    request_id: str | None,
    session_id: str | None,
    trace_id: str | None,
    user: UserContext | None = None,
) -> tuple[list[str], dict[str, int]]:
    follow_max = int(os.environ.get("LLM_FOLLOW_UP_MAX_TOKENS", "256"))
    content, usage = chat_completion(
        client,
        messages=[
            {"role": "system", "content": FOLLOW_UP_PROMPT},
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
        user=user,
    )
    try:
        parsed = json.loads(content)
        items = parsed.get("follow_up_questions") or []
        if isinstance(items, list):
            return [str(x).strip() for x in items if str(x).strip()][:3], usage
    except json.JSONDecodeError:
        pass
    return [], usage
