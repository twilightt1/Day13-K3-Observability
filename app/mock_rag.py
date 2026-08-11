from __future__ import annotations

import time

from .incidents import STATE

CORPUS = {
    "refund": ["Refunds are available within 7 days with proof of purchase."],
    "monitoring": ["Metrics detect incidents, traces localize them, logs explain root cause."],
    "policy": ["Do not expose PII in logs. Use sanitized summaries only."],
}

RAG_SLOW_DELAY_SECONDS = 2.5


class RetrievalTimeoutError(TimeoutError):
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        super().__init__(f"Retrieval exceeded {timeout_ms} ms")


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def retrieve(message: str, *, timeout_ms: int = 0) -> list[str]:
    if timeout_ms < 0:
        raise ValueError("timeout_ms must be zero or positive")
    if STATE["tool_fail"]:
        raise RuntimeError("Vector store timeout")

    delay_seconds = RAG_SLOW_DELAY_SECONDS if STATE["rag_slow"] else 0.0
    if timeout_ms > 0 and delay_seconds * 1000 > timeout_ms:
        _sleep(timeout_ms / 1000)
        raise RetrievalTimeoutError(timeout_ms)
    if delay_seconds:
        _sleep(delay_seconds)

    lowered = message.lower()
    for key, docs in CORPUS.items():
        if key in lowered:
            return docs
    return ["No domain document matched. Use general fallback answer."]
