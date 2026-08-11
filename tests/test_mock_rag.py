from __future__ import annotations

import pytest

from app import mock_rag


@pytest.fixture(autouse=True)
def reset_incidents():
    for name in mock_rag.STATE:
        mock_rag.STATE[name] = False
    yield
    for name in mock_rag.STATE:
        mock_rag.STATE[name] = False


def test_retrieve_returns_matching_document_without_delay(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(mock_rag, "_sleep", sleeps.append)

    docs = mock_rag.retrieve("Explain the refund policy", timeout_ms=1500)

    assert docs == ["Refunds are available within 7 days with proof of purchase."]
    assert sleeps == []


def test_rag_slow_raises_after_the_timeout_budget(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(mock_rag, "_sleep", sleeps.append)
    mock_rag.STATE["rag_slow"] = True

    with pytest.raises(mock_rag.RetrievalTimeoutError) as exc_info:
        mock_rag.retrieve("Explain the refund policy", timeout_ms=1500)

    assert exc_info.value.timeout_ms == 1500
    assert sleeps == [1.5]


def test_zero_timeout_preserves_the_original_slow_behavior(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(mock_rag, "_sleep", sleeps.append)
    mock_rag.STATE["rag_slow"] = True

    docs = mock_rag.retrieve("Explain the refund policy", timeout_ms=0)

    assert docs == ["Refunds are available within 7 days with proof of purchase."]
    assert sleeps == [2.5]


def test_negative_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_ms must be zero or positive"):
        mock_rag.retrieve("Explain the refund policy", timeout_ms=-1)
