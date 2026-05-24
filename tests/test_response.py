"""Standard tool response shape tests."""

from app.ask.response import (
    build_tool_error,
    build_tool_response,
    stream_delta_event,
    stream_meta_event,
)
from app.observability.correlation import UserContext


def test_build_tool_response_shape() -> None:
    user = UserContext(
        user_id="u1",
        user_roles="admin",
        user_groups="eng",
        user_teams="platform",
    )
    body = build_tool_response(
        request_id="req-1",
        session_id="ses-1",
        trace_id="trc-1",
        conversation_id="conv-1",
        tool_name="ask_repo",
        user=user,
        repos=["org/repo"],
        scope="org/repo",
        answer_text="Hello [1]",
        internal_citations=[{"index": 1, "repo": "org/repo", "label": "repo/README", "type": "repository"}],
        readmes={"org/repo": "readme body"},
        code_hits=[],
        follow_up_questions=["Q1?"],
        internal_latency={"github_readme": 10, "github_search": 20, "chat": 100, "follow_up_chat": 50, "total": 200},
        chat_usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        follow_usage={"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
    )
    assert set(body) == {
        "meta",
        "answer",
        "follow_up_questions",
        "latency_ms",
        "usage",
        "status",
    }
    assert body["meta"]["request_id"] == "req-1"
    assert body["meta"]["tool"] == {"name": "ask_repo", "type": "github", "version": "v1"}
    assert body["answer"]["text"] == "Hello [1]"
    assert body["answer"]["citations"][0]["cite_id"] == 1
    assert body["latency_ms"]["retrieve_rerank"] == 30
    assert body["status"] == {"ok": True, "state": "completed"}


def test_build_tool_error_shape() -> None:
    err = build_tool_error(
        "repo not allowed",
        request_id="req-2",
        session_id="ses-2",
        trace_id=None,
        conversation_id="conv-2",
        tool_name="ask_repo",
        repo="bad",
        allowed=["a", "b"],
    )
    assert err["status"]["ok"] is False
    assert err["status"]["message"] == "repo not allowed"
    assert err["meta"]["github"]["allowed"] == ["a", "b"]


def test_stream_events_no_duplicate_meta() -> None:
    meta = stream_meta_event(
        request_id="r",
        session_id="s",
        trace_id="t",
        conversation_id="c",
        tool_name="ask_repo",
        user=None,
        repos=["o/r"],
        scope="o/r",
    )
    assert list(meta) == ["meta"]
    delta = stream_delta_event("chunk")
    assert delta == {"answer": {"text": "chunk"}}
    assert "meta" not in delta
