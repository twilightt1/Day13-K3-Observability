"""Tính số liệu 6 panel dashboard từ log JSONL theo contract config/dashboard.yaml.

Module này tách khỏi lớp hiển thị để số liệu trên dashboard kiểm chứng được bằng test;
`scripts/dashboard.py` chỉ vẽ lại kết quả trả về từ đây.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .metrics import percentile

DEFAULT_LOG_PATH = Path("data/logs.jsonl")


@dataclass(frozen=True)
class SeriesPoint:
    minute: datetime
    value: float


@dataclass(frozen=True)
class PanelResult:
    id: str
    title: str
    unit: str
    values: dict[str, Any]
    threshold_aggregation: str
    threshold_operator: str
    threshold_value: float
    breached: bool
    series: list[SeriesPoint] = field(default_factory=list)


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_events(
    path: Path | str = DEFAULT_LOG_PATH,
    *,
    window_minutes: int = 60,
    now: datetime | None = None,
) -> list[dict]:
    """Đọc log JSONL và giữ lại event nằm trong cửa sổ thời gian, sắp xếp tăng dần."""
    path = Path(path)
    if not path.exists():
        return []

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)

    events: list[tuple[datetime, dict]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # log có thể đang được ghi dở khi dashboard tự refresh
        if not isinstance(event, dict):
            continue
        ts = _parse_ts(event.get("ts"))
        if ts is None or ts < cutoff:
            continue
        events.append((ts, event))

    events.sort(key=lambda item: item[0])
    return [event for _, event in events]


def _numbers(events: list[dict], key: str) -> list[float]:
    return [event[key] for event in events if isinstance(event.get(key), (int, float))]


def _aggregate(
    name: str,
    panel: dict,
    events: list[dict],
    window_minutes: float,
) -> Any:
    fields = panel["fields"]

    if name in {"p50", "p95", "p99"}:
        return percentile([int(value) for value in _numbers(events, fields[0])], int(name[1:]))
    if name == "count":
        return len(events)
    if name == "rate_per_minute":
        return len(events) / window_minutes if window_minutes else 0.0
    if name == "error_rate_pct":
        received = sum(1 for event in events if event.get("event") == "request_received")
        failed = sum(1 for event in events if event.get("event") == "request_failed")
        return (failed / received * 100) if received else 0.0
    if name == "count_by_value":
        return dict(
            Counter(
                event[fields[0]] for event in events if isinstance(event.get(fields[0]), str)
            )
        )
    if name == "total":
        return sum(_numbers(events, fields[0]))
    if name == "sum_by_minute":
        buckets: dict[str, float] = defaultdict(float)
        for event in events:
            ts = _parse_ts(event.get("ts"))
            value = event.get(fields[0])
            if ts is None or not isinstance(value, (int, float)):
                continue
            buckets[ts.replace(second=0, microsecond=0).isoformat()] += value
        return dict(sorted(buckets.items()))
    if name == "sum_by_field":
        return {name_: sum(_numbers(events, name_)) for name_ in fields}
    if name == "mean":
        values = _numbers(events, fields[0])
        return mean(values) if values else 0.0
    raise ValueError(f"Aggregation chưa được hỗ trợ: {name}")


def _violates(value: Any, operator: str, limit: float) -> bool:
    if isinstance(value, dict):
        return any(_violates(item, operator, limit) for item in value.values())
    if not isinstance(value, (int, float)):
        return False
    return value > limit if operator == "lte" else value < limit


def _series(panel: dict, events: list[dict], aggregation: str) -> list[SeriesPoint]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for event in events:
        ts = _parse_ts(event.get("ts"))
        if ts is None:
            continue
        buckets[ts.replace(second=0, microsecond=0)].append(event)

    points: list[SeriesPoint] = []
    for minute in sorted(buckets):
        value = _aggregate(aggregation, panel, buckets[minute], window_minutes=1)
        if isinstance(value, dict):
            value = sum(item for item in value.values() if isinstance(item, (int, float)))
        if isinstance(value, (int, float)):
            points.append(SeriesPoint(minute=minute, value=float(value)))
    return points


def compute_panels(
    events: list[dict],
    contract: dict,
    *,
    now: datetime | None = None,
) -> dict[str, PanelResult]:
    """Tính giá trị từng panel; contract quyết định event, field, aggregation và threshold."""
    dashboard = contract["dashboard"]
    window_minutes = dashboard.get("time_range_minutes", 60)

    panels: dict[str, PanelResult] = {}
    for panel in dashboard["panels"]:
        wanted = set(panel["events"])
        panel_events = [event for event in events if event.get("event") in wanted]

        values = {
            name: _aggregate(name, panel, panel_events, window_minutes)
            for name in panel["aggregations"]
        }

        threshold = panel["threshold"]
        aggregation = threshold["aggregation"]
        operator = threshold["operator"]
        limit = float(threshold["value"])
        # Panel không có dữ liệu thì báo "chưa có số", không phải "vi phạm SLO".
        breached = bool(panel_events) and _violates(values[aggregation], operator, limit)

        panels[panel["id"]] = PanelResult(
            id=panel["id"],
            title=panel["title"],
            unit=panel["unit"],
            values=values,
            threshold_aggregation=aggregation,
            threshold_operator=operator,
            threshold_value=limit,
            breached=breached,
            series=_series(panel, panel_events, aggregation),
        )
    return panels
