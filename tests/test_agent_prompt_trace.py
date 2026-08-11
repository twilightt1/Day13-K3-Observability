from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import agent as agent_module
from app.mock_rag import RetrievalTimeoutError
from structlog.contextvars import bind_contextvars, clear_contextvars


class RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.records.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.records.append(("warning", event, kwargs))


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
    monkeypatch.setattr(agent_module, "log", RecordingLogger())

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


def _run_agent_with(client, monkeypatch, *, agent=None, logger=None):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "log", logger or RecordingLogger())
    agent = agent or agent_module.LabAgent()
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
    metadata = retrieve_span.updates[-1]["metadata"]
    assert metadata["doc_count"] == 1
    assert metadata["degraded"] is False
    assert isinstance(metadata["retrieval_duration_ms"], int)
    assert metadata["retrieval_duration_ms"] >= 0


def test_generation_span_records_token_usage(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    result = _run_agent_with(client, monkeypatch)

    generate_span = client.spans[1]
    metadata = generate_span.updates[-1]["metadata"]
    assert metadata["tokens_out"] == result.tokens_out


def test_agent_uses_default_retrieval_timeout(monkeypatch) -> None:
    monkeypatch.delenv("RETRIEVAL_TIMEOUT_MS", raising=False)

    agent = agent_module.LabAgent()

    assert agent.retrieval_timeout_ms == 1500


def test_agent_accepts_zero_retrieval_timeout(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TIMEOUT_MS", "0")

    agent = agent_module.LabAgent()

    assert agent.retrieval_timeout_ms == 0


@pytest.mark.parametrize("value", ["invalid", "-1"])
def test_agent_rejects_invalid_retrieval_timeout(monkeypatch, value: str) -> None:
    monkeypatch.setenv("RETRIEVAL_TIMEOUT_MS", value)

    with pytest.raises(ValueError, match="RETRIEVAL_TIMEOUT_MS must be an integer >= 0"):
        agent_module.LabAgent()


def test_retrieval_span_records_duration_and_healthy_status(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    _run_agent_with(client, monkeypatch)

    metadata = client.spans[0].updates[-1]["metadata"]
    assert metadata["doc_count"] == 1
    assert metadata["degraded"] is False
    assert isinstance(metadata["retrieval_duration_ms"], int)
    assert metadata["retrieval_duration_ms"] >= 0


def test_agent_converts_only_retrieval_timeout_to_degraded_generation(monkeypatch) -> None:
    client = RecordingLangfuseClient()
    logger = RecordingLogger()

    def timeout(*args, **kwargs):
        raise RetrievalTimeoutError(1500)

    timestamps = iter([10.0, 10.0, 11.5, 11.75])
    monkeypatch.setattr(agent_module, "retrieve", timeout)
    monkeypatch.setattr(agent_module.time, "perf_counter", lambda: next(timestamps))

    result = _run_agent_with(
        client,
        monkeypatch,
        agent=agent_module.LabAgent(retrieval_timeout_ms=1500),
        logger=logger,
    )

    metadata = client.spans[0].updates[-1]["metadata"]
    assert metadata == {
        "doc_count": 0,
        "degraded": True,
        "retrieval_duration_ms": 1500,
        "timeout_ms": 1500,
    }
    assert client.generation_updates[-1]["metadata"]["doc_count"] == 0
    assert result.latency_ms == 1750
    assert logger.records == [
        (
            "warning",
            "retrieval_timed_out",
            {
                "service": "rag",
                "error_type": "RetrievalTimeoutError",
                "retrieval_duration_ms": 1500,
                "timeout_ms": 1500,
                "doc_count": 0,
                "degraded": True,
            },
        )
    ]


def test_agent_does_not_swallow_unrelated_retrieval_failure(monkeypatch) -> None:
    client = RecordingLangfuseClient()

    def fail(*args, **kwargs):
        raise RuntimeError("Vector store timeout")

    monkeypatch.setattr(agent_module, "retrieve", fail)

    with pytest.raises(RuntimeError, match="Vector store timeout"):
        _run_agent_with(client, monkeypatch)
