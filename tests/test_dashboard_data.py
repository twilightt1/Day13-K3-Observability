from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app import dashboard_data

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def contract() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "dashboard.yaml").read_text(encoding="utf-8"))


def _ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _response(minutes_ago: float, **fields) -> dict:
    base = {
        "event": "response_sent",
        "service": "api",
        "level": "info",
        "ts": _ts(minutes_ago),
        "latency_ms": 1000,
        "tokens_in": 100,
        "tokens_out": 200,
        "cost_usd": 0.01,
        "quality_score": 0.9,
    }
    base.update(fields)
    return base


def _received(minutes_ago: float) -> dict:
    return {"event": "request_received", "service": "api", "level": "info", "ts": _ts(minutes_ago)}


def _failed(minutes_ago: float, error_type: str) -> dict:
    return {
        "event": "request_failed",
        "service": "api",
        "level": "error",
        "ts": _ts(minutes_ago),
        "error_type": error_type,
    }


def _write_logs(tmp_path: Path, events: list[dict]) -> Path:
    path = tmp_path / "logs.jsonl"
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_events_keeps_only_events_inside_the_time_window(tmp_path: Path) -> None:
    path = _write_logs(tmp_path, [_received(10), _received(59), _received(61)])

    events = dashboard_data.load_events(path, window_minutes=60, now=NOW)

    assert [event["ts"] for event in events] == [_ts(59), _ts(10)]


def test_load_events_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "logs.jsonl"
    path.write_text(
        json.dumps(_received(5)) + "\nnot-json\n" + json.dumps(_received(4)) + "\n",
        encoding="utf-8",
    )

    events = dashboard_data.load_events(path, window_minutes=60, now=NOW)

    assert len(events) == 2


def test_latency_panel_reports_percentiles_from_response_sent(tmp_path: Path, contract) -> None:
    events = [
        _response(10, latency_ms=1000),
        _response(9, latency_ms=2000),
        _response(8, latency_ms=3000),
        _response(7, latency_ms=4000),
    ]
    path = _write_logs(tmp_path, events)

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["latency"].values == {"p50": 2000.0, "p95": 4000.0, "p99": 4000.0}
    assert panels["latency"].unit == "ms"


def test_traffic_panel_counts_requests_and_rate_per_minute(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_received(10), _received(10), _received(9)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["traffic"].values["count"] == 3
    assert panels["traffic"].values["rate_per_minute"] == pytest.approx(3 / 60)


def test_errors_panel_reports_rate_and_breakdown_by_error_type(tmp_path: Path, contract) -> None:
    events = [
        _received(10),
        _received(9),
        _received(8),
        _received(7),
        _failed(9, "RuntimeError"),
        _failed(8, "TimeoutError"),
    ]
    path = _write_logs(tmp_path, events)

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["errors"].values["error_rate_pct"] == pytest.approx(50.0)
    assert panels["errors"].values["count_by_value"] == {"RuntimeError": 1, "TimeoutError": 1}


def test_cost_panel_totals_spend_over_the_window(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_response(10, cost_usd=0.5), _response(9, cost_usd=0.25)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["cost"].values["total"] == pytest.approx(0.75)


def test_tokens_panel_sums_each_field_separately(tmp_path: Path, contract) -> None:
    events = [
        _response(10, tokens_in=100, tokens_out=200),
        _response(9, tokens_in=50, tokens_out=25),
    ]
    path = _write_logs(tmp_path, events)

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["tokens"].values["sum_by_field"] == {"tokens_in": 150, "tokens_out": 225}


def test_quality_panel_averages_quality_score(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_response(10, quality_score=0.8), _response(9, quality_score=0.6)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["quality"].values["mean"] == pytest.approx(0.7)


def test_lte_threshold_is_breached_when_value_exceeds_the_limit(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_response(10, latency_ms=9000)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["latency"].breached is True


def test_gte_threshold_is_breached_when_value_falls_below_the_limit(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_response(10, quality_score=0.1)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["quality"].breached is True
    assert panels["quality"].threshold_value == 0.75


def test_threshold_is_not_breached_when_value_meets_the_contract(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_response(10, latency_ms=1000, quality_score=0.9)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["latency"].breached is False
    assert panels["quality"].breached is False


def test_dict_valued_threshold_is_breached_when_any_field_exceeds_the_limit(
    tmp_path: Path, contract
) -> None:
    path = _write_logs(tmp_path, [_response(10, tokens_in=10, tokens_out=60_000)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert panels["tokens"].breached is True


def test_panels_stay_empty_and_unbreached_without_data(tmp_path: Path, contract) -> None:
    path = _write_logs(tmp_path, [_received(200)])

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    assert set(panels) == {"latency", "traffic", "errors", "cost", "tokens", "quality"}
    assert panels["latency"].values == {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    assert panels["latency"].breached is False
    assert panels["quality"].breached is False


def test_series_buckets_values_per_minute_for_charting(tmp_path: Path, contract) -> None:
    events = [
        _response(10, cost_usd=0.1),
        _response(10, cost_usd=0.2),
        _response(9, cost_usd=0.4),
    ]
    path = _write_logs(tmp_path, events)

    panels = dashboard_data.compute_panels(
        dashboard_data.load_events(path, window_minutes=60, now=NOW), contract, now=NOW
    )

    series = panels["cost"].series
    assert [round(point.value, 6) for point in series] == [0.3, 0.4]
    assert series[0].minute < series[1].minute
