from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app


@app.get("/_test/unhandled-error")
async def unhandled_error() -> None:
    raise RuntimeError("simulated failure")


def test_middleware_generates_correlation_id_and_response_time_headers() -> None:
    """Catches a middleware regression that returns the placeholder ID."""
    with TestClient(app) as client:
        response = client.get("/health")

    correlation_id = response.headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{8}", correlation_id)
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_middleware_preserves_client_correlation_id() -> None:
    """Catches a middleware regression that discards a caller-provided request ID."""
    with TestClient(app) as client:
        response = client.get("/health", headers={"x-request-id": "req-client01"})

    assert response.headers["x-request-id"] == "req-client01"


def test_unhandled_error_keeps_correlation_id_in_response_header() -> None:
    """Catches an exception response that loses the request correlation ID."""
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/unhandled-error")

    assert response.status_code == 500
    assert response.json() == {"detail": "RuntimeError"}
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
