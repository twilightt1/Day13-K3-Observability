from collections import Counter

from app import metrics
from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_snapshot_calculates_error_rate_from_successes_and_failures(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "TRAFFIC", 4)
    monkeypatch.setattr(metrics, "ERRORS", Counter({"RuntimeError": 1}))

    snapshot = metrics.snapshot()

    assert snapshot["error_rate_pct"] == 20.0
    assert snapshot["error_breakdown"] == {"RuntimeError": 1}
