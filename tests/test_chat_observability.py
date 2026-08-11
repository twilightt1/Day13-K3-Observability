from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config, main as main_module, mock_rag
from app.agent import LabAgent
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-01",
                "session_id": "session-01",
                "feature": "qa",
                "message": "Explain observability",
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]


def test_chat_logs_enriched_request_context_without_raw_user_id(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-01",
                "session_id": "session-01",
                "feature": "qa",
                "message": "Explain observability",
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_event = next(event for event in events if event["event"] == "request_received")
    assert request_event["user_id_hash"] == "2a2006df8771"
    assert request_event["session_id"] == "session-01"
    assert request_event["feature"] == "qa"
    assert request_event["model"] == "claude-sonnet-4-5"
    assert request_event["env"] == "dev"
    assert "student-01" not in json.dumps(request_event)


def test_chat_scrubs_pii_from_enriched_context_before_writing_json_log(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-02",
                "session_id": "student@vinuni.edu.vn",
                "feature": "qa",
                "message": "Explain observability.",
            },
        )

    assert response.status_code == 200
    rendered_log = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in rendered_log
    assert "[REDACTED_EMAIL]" in rendered_log


def test_retrieval_timeout_is_a_correlated_pii_safe_degraded_response(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    monkeypatch.setattr(main_module, "agent", LabAgent(retrieval_timeout_ms=1))
    monkeypatch.setitem(mock_rag.STATE, "rag_slow", True)
    monkeypatch.setattr(mock_rag, "_sleep", lambda _: None)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-incident@example.com",
                "session_id": "cp3-session",
                "feature": "refund",
                "message": "Refund for customer@example.com",
            },
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    timeout_event = next(event for event in events if event["event"] == "retrieval_timed_out")
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert timeout_event["correlation_id"] == response.headers["x-request-id"]
    assert response_event["correlation_id"] == response.headers["x-request-id"]
    assert timeout_event["timeout_ms"] == 1
    assert timeout_event["doc_count"] == 0
    assert timeout_event["degraded"] is True
    rendered_log = log_path.read_text(encoding="utf-8")
    assert "student-incident@example.com" not in rendered_log
    assert "customer@example.com" not in rendered_log
    assert "[REDACTED_EMAIL]" in rendered_log


def test_logging_schema_declares_retrieval_fields() -> None:
    schema = json.loads(Path("config/logging_schema.json").read_text(encoding="utf-8"))

    properties = schema["properties"]
    assert properties["retrieval_duration_ms"] == {"type": ["integer", "null"]}
    assert properties["doc_count"] == {"type": ["integer", "null"]}
    assert properties["degraded"] == {"type": ["boolean", "null"]}
    assert properties["timeout_ms"] == {"type": ["integer", "null"]}
