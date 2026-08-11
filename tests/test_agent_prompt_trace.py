from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module
from structlog.contextvars import bind_contextvars, clear_contextvars


class RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.trace_updates: list[dict] = []
        self.generation_updates: list[dict] = []
        self.spans: list[RecordingSpan] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_trace(self, **kwargs) -> None:
        self.trace_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)

    @contextmanager
    def start_as_current_span(self, *, name: str, **kwargs):
        span = RecordingSpan(name)
        self.spans.append(span)
        yield span


def test_agent_links_prompt_version_to_trace_and_generation(monkeypatch) -> None:
    clear_contextvars()
    bind_contextvars(correlation_id="req-trace001")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
    )

    trace_metadata = client.trace_updates[-1]["metadata"]
    generation_update = client.generation_updates[-1]
    assert trace_metadata == {
        "correlation_id": "req-trace001",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
    }
    assert generation_update["prompt"] is client.prompt
    assert generation_update["metadata"]["prompt_version"] == "3"


def _run_agent_with(client, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    agent = agent_module.LabAgent()
    return agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain refund policy",
    )


def test_agent_opens_a_child_span_per_pipeline_step(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    _run_agent_with(client, monkeypatch)

    assert [span.name for span in client.spans] == ["retrieve-docs", "llm-generate"]


def test_retrieval_span_records_how_many_docs_were_found(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    _run_agent_with(client, monkeypatch)

    retrieve_span = client.spans[0]
    assert retrieve_span.updates[-1]["metadata"]["doc_count"] == 1


def test_generation_span_records_token_usage(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    result = _run_agent_with(client, monkeypatch)

    generate_span = client.spans[1]
    metadata = generate_span.updates[-1]["metadata"]
    assert metadata["tokens_out"] == result.tokens_out
